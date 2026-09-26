// One-off: bake a depth map per painted sky for the parallax shader.
// Run: npm i --no-save @huggingface/transformers && npm run depth
import { pipeline, RawImage } from '@huggingface/transformers';
import { readdirSync } from 'node:fs';

const src = 'src/design-system/imagery', out = 'src/assets/depth';
const depth = await pipeline('depth-estimation', 'onnx-community/depth-anything-v2-small');
for (const f of readdirSync(src).filter((f) => f.endsWith('.webp'))) {
  const { depth: map } = await depth(await RawImage.read(`${src}/${f}`));
  await map.resize(1024, 576).then((m) => m.save(`${out}/${f.replace('.webp', '.png')}`));
  console.log('depth', f);
}
