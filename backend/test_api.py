"""Small contract checks; run with `python -m unittest test_api.py`."""

import io
import os
import tempfile
import unittest

os.environ["PIPELINE_MODE"] = "mock"
_temp_dir = tempfile.TemporaryDirectory()
os.environ["SKETCHSCAPE_DATA_DIR"] = _temp_dir.name

from fastapi.testclient import TestClient  # noqa: E402
import main  # noqa: E402

app = main.app


class ReconstructionApiTests(unittest.TestCase):
    def setUp(self) -> None:
        main.current_scene = main.placeholder_scene()
    def test_mock_job_completes_and_exposes_scene(self) -> None:
        with TestClient(app) as client:
            create = client.post(
                "/v1/reconstructions",
                data={"subject_hint": "tree"},
                files={"image": ("tree.png", io.BytesIO(b"not-a-real-png"), "image/png")},
            )
            self.assertEqual(create.status_code, 202)
            job_id = create.json()["job_id"]
            job = client.get(f"/v1/reconstructions/{job_id}")
            self.assertEqual(job.status_code, 200)
            self.assertEqual(job.json()["status"], "complete")
            self.assertEqual(job.json()["scene"]["meta"]["pipeline"], "mock")

    def test_project_assets_compile_into_versioned_blueprint(self) -> None:
        with TestClient(app) as client:
            project_response = client.post(
                "/v1/projects", json={"name": "Forest room", "description": "AR/VR test"}
            )
            self.assertEqual(project_response.status_code, 201)
            project_id = project_response.json()["project_id"]

            asset_response = client.post(
                f"/v1/projects/{project_id}/assets",
                data={"subject_hint": "ancient tree"},
                files={"image": ("tree.png", io.BytesIO(b"not-a-real-png"), "image/png")},
            )
            self.assertEqual(asset_response.status_code, 202)
            asset = asset_response.json()
            assets = client.get(f"/v1/projects/{project_id}/assets")
            self.assertEqual(assets.status_code, 200)
            asset = assets.json()[0]
            self.assertEqual(asset["status"], "ready")

            blueprint = {
                "experience": {"mode": "ar_vr", "theme": "enchanted forest", "units": "meters"},
                "environment": {"lighting_preset": "warm_twilight", "floor": True},
                "objects": [
                    {
                        "id": "tree_hero",
                        "asset_id": asset["asset_id"],
                        "position": [0, 0, 3],
                        "rotation": [0, 15, 0],
                        "scale": [1, 1, 1],
                        "interactions": ["inspect", "scale"],
                    }
                ],
                "navigation": {"vr": "teleport", "ar": "surface-placement"},
            }
            created = client.post(f"/v1/projects/{project_id}/blueprints", json=blueprint)
            self.assertEqual(created.status_code, 201)
            self.assertEqual(created.json()["revision"], 1)

            published = client.post(f"/v1/projects/{project_id}/blueprints/1/publish")
            self.assertEqual(published.status_code, 200)
            self.assertEqual(published.json()["scene"]["objects"][0]["id"], "tree_hero")
            self.assertEqual(published.json()["scene"]["objects"][0]["actions"], ["scale_by"])
            self.assertEqual(published.json()["scene"]["meta"]["experience"]["mode"], "ar_vr")

            forbidden = client.post(
                "/v1/scene/actions",
                json={"target_id": "tree_hero", "action": "translate_by", "value": [1, 0, 0]},
            )
            self.assertEqual(forbidden.status_code, 403)

    def test_authoring_state_survives_a_restart(self) -> None:
        """A fresh Store reading the same file must rehydrate authoring state."""
        with TestClient(app) as client:
            project_id = client.post(
                "/v1/projects", json={"name": "Durable room", "description": "restart test"}
            ).json()["project_id"]
            asset = client.post(
                f"/v1/projects/{project_id}/assets",
                data={"subject_hint": "persistent lamp"},
                files={"image": ("lamp.png", io.BytesIO(b"not-a-real-png"), "image/png")},
            ).json()
            client.get(f"/v1/projects/{project_id}/assets")  # drive the mock job to ready
            blueprint = {
                "experience": {"mode": "vr", "theme": "night studio", "units": "meters"},
                "environment": {"lighting_preset": "dim", "floor": True},
                "objects": [
                    {
                        "id": "lamp_hero",
                        "asset_id": asset["asset_id"],
                        "position": [0, 0, 2],
                        "rotation": [0, 0, 0],
                        "scale": [1, 1, 1],
                        "interactions": ["inspect"],
                    }
                ],
                "navigation": {"vr": "smooth", "ar": "none"},
            }
            client.post(f"/v1/projects/{project_id}/blueprints", json=blueprint)
            client.post(f"/v1/projects/{project_id}/blueprints/1/publish")

        # Simulate a process restart: build a brand-new Store over the same file.
        from storage import Store  # noqa: E402

        reloaded = Store(main.store._state_path)
        reloaded.load()

        project = reloaded.get_project(project_id)
        self.assertIsNotNone(project)
        self.assertEqual(project.published_revision, 1)
        self.assertEqual(len(project.asset_ids), 1)
        restored_asset = reloaded.get_asset(project.asset_ids[0])
        self.assertIsNotNone(restored_asset)
        self.assertEqual(restored_asset.status, main.AssetStatus.READY)
        self.assertEqual(len(reloaded.list_blueprints(project_id)), 1)
        self.assertEqual(reloaded.list_blueprints(project_id)[0].objects[0].id, "lamp_hero")

    def test_publication_history_is_append_only(self) -> None:
        """Republishing appends a record; it never rewrites earlier history."""
        with TestClient(app) as client:
            project_id = client.post(
                "/v1/projects", json={"name": "Log room", "description": "publication log"}
            ).json()["project_id"]
            asset = client.post(
                f"/v1/projects/{project_id}/assets",
                data={"subject_hint": "log chair"},
                files={"image": ("chair.png", io.BytesIO(b"not-a-real-png"), "image/png")},
            ).json()
            client.get(f"/v1/projects/{project_id}/assets")

            def make_blueprint(scale: float) -> dict:
                return {
                    "experience": {"mode": "desktop", "theme": "log", "units": "meters"},
                    "environment": {"lighting_preset": "neutral", "floor": True},
                    "objects": [
                        {
                            "id": "chair",
                            "asset_id": asset["asset_id"],
                            "position": [0, 0, 2],
                            "rotation": [0, 0, 0],
                            "scale": [scale, scale, scale],
                            "interactions": ["inspect"],
                        }
                    ],
                    "navigation": {"vr": "none", "ar": "none"},
                }

            client.post(f"/v1/projects/{project_id}/blueprints", json=make_blueprint(1.0))
            client.post(f"/v1/projects/{project_id}/blueprints", json=make_blueprint(2.0))

            client.post(f"/v1/projects/{project_id}/blueprints/1/publish")
            client.post(f"/v1/projects/{project_id}/blueprints/2/publish")
            client.post(f"/v1/projects/{project_id}/blueprints/1/publish")

            history = client.get(f"/v1/projects/{project_id}/publications")
            self.assertEqual(history.status_code, 200)
            revisions = [record["revision"] for record in history.json()]
            self.assertEqual(revisions, [1, 2, 1])

    def test_scene_edit_is_bounded(self) -> None:
        with TestClient(app) as client:
            response = client.post("/v1/scene/modify", json={"instruction": "Make the tree twice as tall"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["scene"]["objects"][0]["scale"][1], 2.0)

    def test_structured_interactive_actions_are_discoverable_and_bounded(self) -> None:
        with TestClient(app) as client:
            registry = client.get("/v1/interactives")
            self.assertEqual(registry.status_code, 200)
            tree = next(item for item in registry.json()["interactives"] if item["id"] == "tree_1")
            self.assertEqual(tree["actions"], ["scale_by", "translate_by", "rotate_by"])

            update = client.post(
                "/v1/scene/actions",
                json={"target_id": "tree_1", "action": "translate_by", "value": [1, 0, -1]},
            )
            self.assertEqual(update.status_code, 200)
            self.assertEqual(update.json()["scene"]["objects"][0]["position"], [-1.1, 0.0, 6.0])

            rejected = client.post(
                "/v1/scene/actions",
                json={"target_id": "tree_1", "action": "translate_by", "value": [1000, 0, 0]},
            )
            self.assertEqual(rejected.status_code, 422)


class MultiViewProvenanceTests(unittest.TestCase):
    """Verify per-view reconstruction provenance on catalog assets."""

    def _make_project(self, client, name: str = "Multi-view room") -> str:
        return client.post(
            "/v1/projects", json={"name": name, "description": ""}
        ).json()["project_id"]

    def _create_asset(self, client, project_id: str, hint: str = "vase") -> dict:
        r = client.post(
            f"/v1/projects/{project_id}/assets",
            data={"subject_hint": hint},
            files={"image": ("vase.png", io.BytesIO(b"PNG1"), "image/png")},
        )
        self.assertEqual(r.status_code, 202)
        return r.json()

    def test_asset_creation_seeds_first_view(self) -> None:
        """Creating an asset via POST /assets must seed views[0] with correct metadata."""
        with TestClient(app) as client:
            pid = self._make_project(client)
            asset_stub = self._create_asset(client, pid, hint="blue lamp")
            asset_id = asset_stub["asset_id"]

            # Fetch the full asset record (single-asset GET endpoint).
            r = client.get(f"/v1/projects/{pid}/assets/{asset_id}")
            self.assertEqual(r.status_code, 200)
            asset = r.json()

            self.assertEqual(len(asset["views"]), 1)
            view0 = asset["views"][0]
            self.assertEqual(view0["view_index"], 0)
            self.assertEqual(view0["subject_hint"], "blue lamp")
            # job_id must be populated and match the legacy top-level field.
            self.assertIsNotNone(view0["reconstruction_job_id"])
            self.assertEqual(
                view0["reconstruction_job_id"],
                asset["reconstruction_job_id"],
            )

    def test_add_second_view_registers_new_view(self) -> None:
        """POST /assets/{id}/views must append a view with view_index=1."""
        with TestClient(app) as client:
            pid = self._make_project(client)
            asset_id = self._create_asset(client, pid)["asset_id"]

            r = client.post(
                f"/v1/projects/{pid}/assets/{asset_id}/views",
                data={"subject_hint": "vase from left"},
                files={"image": ("vase2.png", io.BytesIO(b"PNG2"), "image/png")},
            )
            self.assertEqual(r.status_code, 202)
            view = r.json()
            self.assertEqual(view["view_index"], 1)
            self.assertEqual(view["subject_hint"], "vase from left")

            # Views endpoint must return both views in order.
            views_r = client.get(f"/v1/projects/{pid}/assets/{asset_id}/views")
            self.assertEqual(views_r.status_code, 200)
            indices = [v["view_index"] for v in views_r.json()]
            self.assertEqual(indices, [0, 1])

    def test_asset_ready_when_first_view_completes(self) -> None:
        """Asset must become READY and artifact_url promoted once view 0 job completes."""
        with TestClient(app) as client:
            pid = self._make_project(client)
            asset_id = self._create_asset(client, pid, hint="chair")["asset_id"]

            # Mock pipeline completes jobs synchronously inside TestClient.
            # Fetching assets drives the status update into the store.
            assets = client.get(f"/v1/projects/{pid}/assets")
            self.assertEqual(assets.status_code, 200)
            self.assertEqual(assets.json()[0]["status"], "ready")

            # The top-level artifact_url must match the first READY view's url.
            full = client.get(f"/v1/projects/{pid}/assets/{asset_id}")
            view0 = full.json()["views"][0]
            self.assertEqual(view0["status"], "ready")
            self.assertEqual(full.json()["artifact_url"], view0["artifact_url"])

    def test_view_status_syncs_on_worker_callback(self) -> None:
        """Worker callback must update the matching AssetView by job_id."""
        with TestClient(app) as client:
            pid = self._make_project(client)
            # Create asset (view 0 completes via mock immediately).
            asset_id = self._create_asset(client, pid, hint="pot")["asset_id"]

            # Add a second view — its job_id is fresh and has not run yet.
            v1 = client.post(
                f"/v1/projects/{pid}/assets/{asset_id}/views",
                data={"subject_hint": "pot from above"},
                files={"image": ("pot2.png", io.BytesIO(b"PNG2"), "image/png")},
            ).json()
            job2_id = v1["reconstruction_job_id"]

            # Simulate a real worker posting a successful result for view 1.
            ply_bytes = b"ply\nformat ascii 1.0\nend_header\n"
            mask_bytes = b"\x89PNG"
            worker_token = os.environ.get("SKETCHSCAPE_WORKER_TOKEN", "")
            callback = client.post(
                f"/v1/internal/reconstructions/{job2_id}/result",
                data={
                    "result": '{"status":"complete","object_label":"pot"}',
                    "worker_token": worker_token,
                },
                files={
                    "ply": ("reconstruction.ply", io.BytesIO(ply_bytes), "application/octet-stream"),
                    "mask": ("mask.png", io.BytesIO(mask_bytes), "image/png"),
                },
            )
            self.assertEqual(callback.status_code, 200)

            # View 1 must now be READY with an artifact URL.
            views = client.get(f"/v1/projects/{pid}/assets/{asset_id}/views").json()
            view1 = next(v for v in views if v["view_index"] == 1)
            self.assertEqual(view1["status"], "ready")
            self.assertIsNotNone(view1["artifact_url"])

            # The asset must remain READY (view 0 was already ready).
            asset = client.get(f"/v1/projects/{pid}/assets/{asset_id}").json()
            self.assertEqual(asset["status"], "ready")

    def test_second_view_failure_does_not_demote_ready_asset(self) -> None:
        """A failed second view must not change asset status when view 0 is READY."""
        with TestClient(app) as client:
            pid = self._make_project(client)
            # View 0 completes via mock immediately.
            asset_id = self._create_asset(client, pid, hint="lamp")["asset_id"]

            # Add a second view and simulate its job failing.
            v1 = client.post(
                f"/v1/projects/{pid}/assets/{asset_id}/views",
                data={"subject_hint": "lamp from side"},
                files={"image": ("lamp2.png", io.BytesIO(b"PNG2"), "image/png")},
            ).json()
            job2_id = v1["reconstruction_job_id"]

            worker_token = os.environ.get("SKETCHSCAPE_WORKER_TOKEN", "")
            client.post(
                f"/v1/internal/reconstructions/{job2_id}/result",
                data={
                    "result": '{"status":"failed","object_label":"lamp","error":"VRAM OOM"}',
                    "worker_token": worker_token,
                },
            )

            # Asset must still be READY because view 0 succeeded.
            asset = client.get(f"/v1/projects/{pid}/assets/{asset_id}").json()
            self.assertEqual(asset["status"], "ready")
            views = client.get(f"/v1/projects/{pid}/assets/{asset_id}/views").json()
            ready_views  = [v for v in views if v["status"] == "ready"]
            failed_views = [v for v in views if v["status"] == "failed"]
            self.assertEqual(len(ready_views),  1)
            self.assertEqual(len(failed_views), 1)

    def test_multi_view_asset_compiles_into_blueprint(self) -> None:
        """A multi-view READY asset must compile into a blueprint correctly."""
        with TestClient(app) as client:
            pid = self._make_project(client)
            asset_id = self._create_asset(client, pid, hint="statue")["asset_id"]

            # Drive view 0 to READY via the list endpoint.
            client.get(f"/v1/projects/{pid}/assets")

            blueprint = {
                "experience": {"mode": "vr", "theme": "museum", "units": "meters"},
                "environment": {"lighting_preset": "bright", "floor": True},
                "objects": [
                    {
                        "id": "statue_1",
                        "asset_id": asset_id,
                        "position": [0, 0, 3],
                        "rotation": [0, 0, 0],
                        "scale": [1, 1, 1],
                        "interactions": ["inspect"],
                    }
                ],
                "navigation": {"vr": "teleport", "ar": "none"},
            }
            created = client.post(f"/v1/projects/{pid}/blueprints", json=blueprint)
            self.assertEqual(created.status_code, 201)

            published = client.post(f"/v1/projects/{pid}/blueprints/1/publish")
            self.assertEqual(published.status_code, 200)
            self.assertEqual(published.json()["scene"]["objects"][0]["id"], "statue_1")


class ContributorContributionApiTests(unittest.TestCase):
    """Verify the Shared Room contributor/contribution endpoints (Build Plan step 2)."""

    def _make_project(self, client, name: str = "Shared room") -> str:
        return client.post(
            "/v1/projects", json={"name": name, "description": ""}
        ).json()["project_id"]

    def _create_ready_asset(self, client, project_id: str, hint: str = "object") -> dict:
        r = client.post(
            f"/v1/projects/{project_id}/assets",
            data={"subject_hint": hint},
            files={"image": (f"{hint}.png", io.BytesIO(b"PNG-DATA"), "image/png")},
        )
        self.assertEqual(r.status_code, 202)
        asset_id = r.json()["asset_id"]
        # The mock pipeline completes as a background task; fetching the
        # asset drives the settled status into the response, same pattern
        # as MultiViewProvenanceTests.
        full = client.get(f"/v1/projects/{project_id}/assets/{asset_id}")
        self.assertEqual(full.status_code, 200)
        asset = full.json()
        self.assertEqual(asset["status"], "ready")
        return asset

    def test_three_contributors_register_and_contribute(self) -> None:
        """N-ary check: three (not two) contributors, one contribution each."""
        with TestClient(app) as client:
            pid = self._make_project(client)

            contributors = []
            for name in ["Alice", "Bo", "Cass"]:
                r = client.post(f"/v1/projects/{pid}/contributors", json={"display_name": name})
                self.assertEqual(r.status_code, 201)
                body = r.json()
                self.assertEqual(body["display_name"], name)
                self.assertEqual(body["project_id"], pid)
                contributors.append(body)
            self.assertEqual(len(contributors), 3)

            listed_contributors = client.get(f"/v1/projects/{pid}/contributors")
            self.assertEqual(listed_contributors.status_code, 200)
            self.assertEqual(
                {c["contributor_id"] for c in listed_contributors.json()},
                {c["contributor_id"] for c in contributors},
            )

            contributions = []
            for index, contributor in enumerate(contributors):
                asset = self._create_ready_asset(client, pid, hint=f"keepsake-{index}")
                r = client.post(
                    f"/v1/projects/{pid}/contributions",
                    json={
                        "contributor_id": contributor["contributor_id"],
                        "asset_id": asset["asset_id"],
                        "source_type": "photo",
                        "memory_text": f"Memory number {index}",
                    },
                )
                self.assertEqual(r.status_code, 201)
                body = r.json()
                self.assertEqual(body["contributor_id"], contributor["contributor_id"])
                self.assertEqual(body["asset_id"], asset["asset_id"])
                contributions.append(body)
            self.assertEqual(len(contributions), 3)

            listed_contributions = client.get(f"/v1/projects/{pid}/contributions")
            self.assertEqual(listed_contributions.status_code, 200)
            self.assertEqual(
                {c["contribution_id"] for c in listed_contributions.json()},
                {c["contribution_id"] for c in contributions},
            )

    def test_contribution_against_non_ready_asset_is_rejected(self) -> None:
        with TestClient(app) as client:
            pid = self._make_project(client)
            contributor = client.post(
                f"/v1/projects/{pid}/contributors", json={"display_name": "Dana"}
            ).json()

            asset_response = client.post(
                f"/v1/projects/{pid}/assets",
                data={"subject_hint": "broken lamp"},
                files={"image": ("lamp.png", io.BytesIO(b"PNG1"), "image/png")},
            )
            self.assertEqual(asset_response.status_code, 202)
            asset = asset_response.json()
            job_id = asset["reconstruction_job_id"]

            # Force the asset's only view to FAILED via the worker callback,
            # the same mechanism MultiViewProvenanceTests uses.
            worker_token = os.environ.get("SKETCHSCAPE_WORKER_TOKEN", "")
            failed = client.post(
                f"/v1/internal/reconstructions/{job_id}/result",
                data={
                    "result": '{"status":"failed","object_label":"lamp","error":"VRAM OOM"}',
                    "worker_token": worker_token,
                },
            )
            self.assertEqual(failed.status_code, 200)
            asset_after = client.get(f"/v1/projects/{pid}/assets/{asset['asset_id']}").json()
            self.assertEqual(asset_after["status"], "failed")

            r = client.post(
                f"/v1/projects/{pid}/contributions",
                json={
                    "contributor_id": contributor["contributor_id"],
                    "asset_id": asset["asset_id"],
                    "source_type": "photo",
                    "memory_text": "",
                },
            )
            self.assertGreaterEqual(r.status_code, 400)
            self.assertLess(r.status_code, 500)

            # Nothing should have been recorded against the project.
            self.assertEqual(client.get(f"/v1/projects/{pid}/contributions").json(), [])


class ConnectionComposeApiTests(unittest.TestCase):
    """Verify the mock connection/compose endpoint (Build Plan step 5)."""

    def _make_project(self, client, name: str = "Compose room") -> str:
        return client.post(
            "/v1/projects", json={"name": name, "description": ""}
        ).json()["project_id"]

    def _contribute(self, client, project_id: str, name: str, hint: str, memory: str) -> dict:
        contributor = client.post(
            f"/v1/projects/{project_id}/contributors", json={"display_name": name}
        ).json()
        r = client.post(
            f"/v1/projects/{project_id}/assets",
            data={"subject_hint": hint},
            files={"image": (f"{hint}.png", io.BytesIO(b"PNG-DATA"), "image/png")},
        )
        self.assertEqual(r.status_code, 202)
        asset = client.get(f"/v1/projects/{project_id}/assets/{r.json()['asset_id']}").json()
        self.assertEqual(asset["status"], "ready")
        r = client.post(
            f"/v1/projects/{project_id}/contributions",
            json={
                "contributor_id": contributor["contributor_id"],
                "asset_id": asset["asset_id"],
                "source_type": "photo",
                "memory_text": memory,
            },
        )
        self.assertEqual(r.status_code, 201)
        return r.json()

    def _assert_composes(self, client, project_id: str, contributions: list[dict]) -> dict:
        r = client.post(f"/v1/projects/{project_id}/connection/compose")
        self.assertEqual(r.status_code, 201, r.text)
        body = r.json()
        insight, blueprint = body["insight"], body["blueprint"]
        self.assertEqual(insight["backend"], "mock")
        self.assertEqual(blueprint["experience"]["theme"], insight["theme"])
        self.assertEqual(len(blueprint["objects"]), len(contributions))
        self.assertEqual(len(insight["placement_rationale"]), len(contributions))
        self.assertEqual(
            {item["asset_id"] for item in insight["placement_rationale"]},
            {item["asset_id"] for item in contributions},
        )
        # The proposal must pass the same READY-asset check blueprint creation uses.
        validated = client.post(f"/v1/projects/{project_id}/blueprints/validate", json=blueprint)
        self.assertEqual(validated.status_code, 200, validated.text)
        return body

    def test_two_contributions_compose_deterministically(self) -> None:
        with TestClient(app) as client:
            pid = self._make_project(client)
            contributions = [
                self._contribute(client, pid, "Alice", "mug", "My grandma's tea every morning"),
                self._contribute(client, pid, "Bo", "cookbook", "We baked from this every Sunday"),
            ]
            first = self._assert_composes(client, pid, contributions)
            second = self._assert_composes(client, pid, contributions)
            self.assertEqual(first["insight"]["theme"], second["insight"]["theme"])
            self.assertEqual(first["insight"]["explanation"], second["insight"]["explanation"])
            self.assertEqual(first["blueprint"], second["blueprint"])
            self.assertEqual(first["insight"]["theme"], "Around the kitchen table")
            # Each pass appends a new insight revision.
            self.assertEqual(first["insight"]["revision"], 1)
            self.assertEqual(second["insight"]["revision"], 2)

            created = client.post(f"/v1/projects/{pid}/blueprints", json=first["blueprint"])
            self.assertEqual(created.status_code, 201, created.text)

    def test_four_contributions_compose(self) -> None:
        with TestClient(app) as client:
            pid = self._make_project(client)
            contributions = [
                self._contribute(client, pid, "Alice", "shell", "Found on the beach the summer we met"),
                self._contribute(client, pid, "Bo", "paddle", "Our first boat on the lake"),
                self._contribute(client, pid, "Cass", "lamp", ""),
                self._contribute(client, pid, "Dev", "towel", "Swimming lessons with my brother"),
            ]
            body = self._assert_composes(client, pid, contributions)
            self.assertEqual(body["insight"]["theme"], "By the water")
            positions = {tuple(item["position"]) for item in body["blueprint"]["objects"]}
            self.assertEqual(len(positions), 4)
            for name in ["Alice", "Bo", "Cass", "Dev"]:
                self.assertIn(name, body["insight"]["explanation"])

    def test_three_contributor_room_is_attributed_and_edits_are_owner_only(self) -> None:
        """Step 8: the published scene says who owns each object, and a
        contributor session may only edit its own objects."""
        with TestClient(app) as client:
            pid = self._make_project(client)
            contributions = [
                self._contribute(client, pid, "Alice", "mug", "Tea at grandma's"),
                self._contribute(client, pid, "Bo", "guitar", "First song I learned"),
                self._contribute(client, pid, "Cass", "kite", ""),
            ]
            composed = self._assert_composes(client, pid, contributions)
            revision = client.post(f"/v1/projects/{pid}/blueprints", json=composed["blueprint"]).json()["revision"]
            published = client.post(f"/v1/projects/{pid}/blueprints/{revision}/publish")
            self.assertEqual(published.status_code, 200, published.text)
            scene = published.json()["scene"]

            social = scene["meta"]["social"]
            self.assertEqual(social["version"], 1)
            self.assertEqual(len(social["objects"]), 3)
            by_contribution = {item["contribution_id"]: item for item in contributions}
            object_ids = {item["id"] for item in scene["objects"]}
            for entry in social["objects"]:
                self.assertIn(entry["object_id"], object_ids)
                self.assertEqual(
                    entry["contributor_id"], by_contribution[entry["contribution_id"]]["contributor_id"]
                )
            self.assertEqual(
                {entry["contributor_display_name"] for entry in social["objects"]}, {"Alice", "Bo", "Cass"}
            )
            self.assertEqual(len({entry["attribution_color"] for entry in social["objects"]}), 3)

            alice, bo = social["objects"][0], social["objects"][1]
            edit = {"target_id": alice["object_id"], "action": "rotate_by", "value": [0.0, 15.0, 0.0]}
            rejected = client.post("/v1/scene/actions", json={**edit, "contributor_id": bo["contributor_id"]})
            self.assertEqual(rejected.status_code, 403)
            accepted = client.post("/v1/scene/actions", json={**edit, "contributor_id": alice["contributor_id"]})
            self.assertEqual(accepted.status_code, 200, accepted.text)
            # Authoring (MCP/editor) callers without a contributor keep working.
            authoring = client.post("/v1/scene/actions", json=edit)
            self.assertEqual(authoring.status_code, 200, authoring.text)

    def test_blueprint_with_mismatched_contribution_is_rejected(self) -> None:
        with TestClient(app) as client:
            pid = self._make_project(client)
            contributions = [
                self._contribute(client, pid, "Alice", "mug", ""),
                self._contribute(client, pid, "Bo", "guitar", ""),
            ]
            blueprint = self._assert_composes(client, pid, contributions)["blueprint"]
            first, second = blueprint["objects"][0], blueprint["objects"][1]
            first["contribution_id"], second["contribution_id"] = second["contribution_id"], first["contribution_id"]
            r = client.post(f"/v1/projects/{pid}/blueprints", json=blueprint)
            self.assertEqual(r.status_code, 422)

    def test_compose_below_min_contributors_is_409(self) -> None:
        with TestClient(app) as client:
            pid = self._make_project(client)
            r = client.post(f"/v1/projects/{pid}/connection/compose")
            self.assertEqual(r.status_code, 409)
            self._contribute(client, pid, "Solo", "kite", "Windy afternoons")
            r = client.post(f"/v1/projects/{pid}/connection/compose")
            self.assertEqual(r.status_code, 409)


class RevisionConcurrencyApiTests(unittest.TestCase):
    """Build Plan step 15: based_on_revision, 409 on stale writes, LIVE pointer."""

    def _make_project(self, client, name: str = "Concurrency room") -> str:
        return client.post(
            "/v1/projects", json={"name": name, "description": ""}
        ).json()["project_id"]

    def _create_ready_asset(self, client, project_id: str, hint: str = "object") -> dict:
        r = client.post(
            f"/v1/projects/{project_id}/assets",
            data={"subject_hint": hint},
            files={"image": (f"{hint}.png", io.BytesIO(b"PNG-DATA"), "image/png")},
        )
        self.assertEqual(r.status_code, 202)
        asset_id = r.json()["asset_id"]
        full = client.get(f"/v1/projects/{project_id}/assets/{asset_id}")
        self.assertEqual(full.status_code, 200)
        asset = full.json()
        self.assertEqual(asset["status"], "ready")
        return asset

    def _blueprint_payload(self, asset_id: str, scale: float = 1.0) -> dict:
        return {
            "experience": {"mode": "vr", "theme": "concurrency test", "units": "meters"},
            "environment": {"lighting_preset": "neutral", "floor": True},
            "objects": [
                {
                    "id": "hero",
                    "asset_id": asset_id,
                    "position": [0, 0, 2],
                    "rotation": [0, 0, 0],
                    "scale": [scale, scale, scale],
                    "interactions": ["inspect"],
                }
            ],
            "navigation": {"vr": "none", "ar": "none"},
        }

    def test_create_with_base_revision_zero_succeeds_when_nothing_published(self) -> None:
        with TestClient(app) as client:
            pid = self._make_project(client)
            asset = self._create_ready_asset(client, pid)
            created = client.post(
                f"/v1/projects/{pid}/blueprints",
                params={"base_revision": 0},
                json=self._blueprint_payload(asset["asset_id"]),
            )
            self.assertEqual(created.status_code, 201)
            self.assertEqual(created.json()["revision"], 1)
            self.assertEqual(created.json()["based_on_revision"], 0)

    def test_create_with_stale_base_revision_is_409_with_published_revision(self) -> None:
        with TestClient(app) as client:
            pid = self._make_project(client)
            asset = self._create_ready_asset(client, pid)

            first = client.post(
                f"/v1/projects/{pid}/blueprints",
                params={"base_revision": 0},
                json=self._blueprint_payload(asset["asset_id"]),
            )
            self.assertEqual(first.status_code, 201)
            published = client.post(f"/v1/projects/{pid}/blueprints/1/publish")
            self.assertEqual(published.status_code, 200)

            # Someone still building on the old "nothing published" baseline.
            stale = client.post(
                f"/v1/projects/{pid}/blueprints",
                params={"base_revision": 0},
                json=self._blueprint_payload(asset["asset_id"], scale=2.0),
            )
            self.assertEqual(stale.status_code, 409)
            body = stale.json()
            self.assertIn("detail", body)
            self.assertEqual(body["published_revision"], 1)

    def test_two_drafts_on_same_base_only_first_publishes(self) -> None:
        with TestClient(app) as client:
            pid = self._make_project(client)
            asset = self._create_ready_asset(client, pid)

            base = client.post(
                f"/v1/projects/{pid}/blueprints",
                params={"base_revision": 0},
                json=self._blueprint_payload(asset["asset_id"]),
            )
            self.assertEqual(base.status_code, 201)
            client.post(f"/v1/projects/{pid}/blueprints/1/publish")

            draft_a = client.post(
                f"/v1/projects/{pid}/blueprints",
                params={"base_revision": 1},
                json=self._blueprint_payload(asset["asset_id"], scale=2.0),
            ).json()
            draft_b = client.post(
                f"/v1/projects/{pid}/blueprints",
                params={"base_revision": 1},
                json=self._blueprint_payload(asset["asset_id"], scale=3.0),
            ).json()
            self.assertEqual(draft_a["based_on_revision"], 1)
            self.assertEqual(draft_b["based_on_revision"], 1)

            publish_a = client.post(
                f"/v1/projects/{pid}/blueprints/{draft_a['revision']}/publish"
            )
            self.assertEqual(publish_a.status_code, 200)

            publish_b = client.post(
                f"/v1/projects/{pid}/blueprints/{draft_b['revision']}/publish"
            )
            self.assertEqual(publish_b.status_code, 409)
            self.assertEqual(publish_b.json()["published_revision"], draft_a["revision"])

    def test_legacy_draft_without_base_revision_still_publishes_and_rolls_back(self) -> None:
        """Manual authoring (no base_revision) keeps today's behavior, including
        deliberately republishing an older revision."""
        with TestClient(app) as client:
            pid = self._make_project(client)
            asset = self._create_ready_asset(client, pid)

            v1 = client.post(
                f"/v1/projects/{pid}/blueprints", json=self._blueprint_payload(asset["asset_id"], 1.0)
            ).json()
            v2 = client.post(
                f"/v1/projects/{pid}/blueprints", json=self._blueprint_payload(asset["asset_id"], 2.0)
            ).json()
            self.assertIsNone(v1["based_on_revision"])
            self.assertIsNone(v2["based_on_revision"])

            self.assertEqual(
                client.post(f"/v1/projects/{pid}/blueprints/{v1['revision']}/publish").status_code, 200
            )
            self.assertEqual(
                client.post(f"/v1/projects/{pid}/blueprints/{v2['revision']}/publish").status_code, 200
            )
            # Deliberate rollback to the older legacy revision must still work.
            rollback = client.post(f"/v1/projects/{pid}/blueprints/{v1['revision']}/publish")
            self.assertEqual(rollback.status_code, 200)

            compiled = client.get(f"/v1/projects/{pid}/compiled-scene")
            self.assertEqual(compiled.status_code, 200)
            self.assertEqual(compiled.json()["scene"]["objects"][0]["scale"], [1.0, 1.0, 1.0])

    def test_compiled_scene_reads_the_live_pointer(self) -> None:
        with TestClient(app) as client:
            pid = self._make_project(client)
            asset = self._create_ready_asset(client, pid)

            client.post(
                f"/v1/projects/{pid}/blueprints",
                params={"base_revision": 0},
                json=self._blueprint_payload(asset["asset_id"]),
            )
            client.post(f"/v1/projects/{pid}/blueprints/1/publish")

            self.assertEqual(main.store.get_live_revision(pid), 1)
            compiled = client.get(f"/v1/projects/{pid}/compiled-scene")
            self.assertEqual(compiled.status_code, 200)


if __name__ == "__main__":
    unittest.main()
