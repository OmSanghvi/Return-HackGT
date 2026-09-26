// A painted window drawn straight into screen space. It fills a DOM rect (rounded frame or arch),
// fakes a camera inside the painting using its depth map, and can dissolve into mist.
// The quad covers only the DOM rect (plus room for the portal's halo), so no fragments run outside it.
export const vertex = /* glsl */ `
  uniform vec4 uRect;
  uniform vec2 uRes;
  uniform float uDpr, uArch;
  void main() {
    float m = uArch > 0.5 ? 96.0 : 2.0;
    float mBot = uArch > 0.5 ? 0.35 * uRect.w : 0.0;   // extra room below the arch, for its reflection
    vec2 sz = uRect.zw + 2.0 * m + vec2(0.0, mBot);
    vec2 px = uRect.xy - m + vec2(position.x + 0.5, 0.5 - position.y) * sz;   // keep the winding (y flips below)
    vec2 ndc = px * uDpr / uRes * 2.0 - 1.0;
    gl_Position = vec4(ndc.x, -ndc.y, 0.0, 1.0);
  }
`;

export const fragment = /* glsl */ `
  precision highp float;
  uniform sampler2D uTexA, uDepA, uTexB, uDepB;
  uniform float uAspA, uAspB, uMix, uMist, uTime, uZoom, uRadius, uDpr, uArch, uAlpha, uHalo, uLight, uDusk, uBlur, uPetals, uPhoto;
  uniform vec4 uRect;      // css px, top-left origin: x, y, w, h
  uniform vec2 uRes, uPointer;
  uniform vec3 uFog;

  float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
  float noise(vec2 p) {
    vec2 i = floor(p), f = fract(p); f = f * f * (3.0 - 2.0 * f);
    return mix(mix(hash(i), hash(i + vec2(1, 0)), f.x), mix(hash(i + vec2(0, 1)), hash(i + vec2(1, 1)), f.x), f.y);
  }
  float fbm(vec2 p) { float v = 0.0, a = 0.5; for (int i = 0; i < 3; i++) { v += a * noise(p); p *= 2.03; a *= 0.5; } return v; }

  float sdBox(vec2 p, vec2 b, float r) { vec2 q = abs(p) - b + r; return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r; }
  float sdArch(vec2 p, vec2 b) {
    float r = b.x;
    return min(sdBox(p - vec2(0.0, r * 0.5), vec2(b.x, b.y - r * 0.5), 0.0), length(p - vec2(0.0, -b.y + r)) - r);
  }

  // rgb + the final refined depth sample, so the caller can drive depth-based effects (stars, fireflies).
  vec4 paint(sampler2D tex, sampler2D dep, float asp, vec2 luv, vec2 size, float zoom, float blur) {
    float cAsp = size.x / size.y;
    vec2 s = cAsp > asp ? vec2(1.0, asp / cAsp) : vec2(cAsp / asp, 1.0);
    float ang = uTime * 6.2831 / 60.0;                     // 60s drift (duration-drift)
    vec2 uv = (luv - 0.5) * s * (0.9 - 0.012 * sin(ang)) + 0.5;
    uv += vec2(sin(ang), cos(ang * 0.7)) * 0.006;
    uv.y = 1.0 - uv.y;
    vec2 focus = vec2(0.5, 0.55);
    vec2 p = uv;
    float d = 0.0;
    for (int i = 0; i < 2; i++) {                           // refine: offset by the depth at the displaced point
      d = texture2D(dep, p).r;
      vec2 q = focus + (uv - focus) / (1.0 + zoom * (0.12 + 0.9 * d));
      q -= uPointer * vec2(1.0, -1.0) * (d - 0.25) * 0.065;
      q.x += (1.0 - smoothstep(0.0, 0.12, d)) * 0.012 * sin(uTime * 0.05);   // the sky slides a little on its own
      p = q;
    }
    return vec4(texture2D(tex, clamp(p, 0.001, 0.999), blur).rgb, d);
  }

  // Sparse hash-grid points, placed and animated from a single hash() lookup per pixel.
  float starField(vec2 luv) {
    vec2 sc = luv * vec2(90.0, 50.0);
    vec2 id = floor(sc);
    float h = hash(id);
    vec2 pt = id + vec2(fract(h * 13.7), fract(h * 7.3));
    float d = length(sc - pt);
    float star = smoothstep(0.06, 0.0, d);
    float twinkle = 0.6 + 0.4 * sin(uTime * (1.5 + 2.0 * h) + h * 6.2831);
    return star * twinkle;
  }
  float fireflyField(vec2 luv) {
    vec2 fc = luv * vec2(28.0, 16.0);
    vec2 id = floor(fc);
    float h = hash(id);
    float lit = step(0.6, h);
    vec2 drift = vec2(sin(uTime * 0.6 + h * 6.2831), cos(uTime * 0.5 + h * 4.0)) * 0.25;
    vec2 pt = id + vec2(fract(h * 17.0), fract(h * 5.0)) + drift;
    float d = length(fc - pt);
    float glow = smoothstep(0.35, 0.0, d) * lit;
    float twinkle = 0.5 + 0.5 * sin(uTime * (0.4 + 0.6 * h) + h * 6.2831);
    return glow * twinkle;
  }

  // Two hash-grid petal layers (near: bigger/faster, far: smaller/slower), one hash() each. Falling
  // diagonally, per-cell jitter/sway/spin, drawn as a soft rotated ellipse, nudged off the pointer.
  vec4 petalLayer(vec2 p, float speedY, float speedX, float thresh, float scale) {
    vec2 id = floor(p);
    float h = hash(id);
    if (h < thresh) return vec4(0.0);
    vec2 f = fract(p) - 0.5;
    f += (vec2(fract(h * 13.0), fract(h * 29.0)) - 0.5) * 0.5;            // jitter
    f.x += sin(uTime * 1.1 + h * 6.2831) * 0.1;                            // sway
    float ang = h * 6.2831 + uTime * (0.3 + 0.4 * h);                      // slow spin
    float ca = cos(ang), sa = sin(ang);
    vec2 r = mat2(ca, -sa, sa, ca) * f;
    float d = length(r * vec2(1.0, 2.2)) / scale;
    float petal = smoothstep(0.5, 0.15, d);
    float core = smoothstep(0.22, 0.0, d);
    vec3 blossom = mix(vec3(0.953, 0.663, 0.788), vec3(1.0), core);
    return vec4(blossom * petal, petal);
  }
  vec4 petalField(vec2 luv, vec2 size) {
    vec2 asp = vec2(size.x / size.y, 1.0);
    vec2 d = luv - (uPointer + 0.5);
    vec2 luvA = luv * asp + normalize(d + 1e-4) * 0.03 * exp(-dot(d, d) * 18.0) * asp;
    vec4 near = petalLayer(luvA * vec2(10.0, 6.0) + vec2(uTime * 2.2, uTime * 3.4), 3.4, 2.2, 0.65, 1.0);
    vec4 far = petalLayer(luvA * vec2(22.0, 13.0) + vec2(uTime * 1.1, uTime * 1.7), 1.7, 1.1, 0.65, 0.6);
    return near.a > far.a ? near : far;
  }

  void main() {
    vec2 px = vec2(gl_FragCoord.x, uRes.y - gl_FragCoord.y) / uDpr;
    vec2 size = uRect.zw;
    vec2 c = px - uRect.xy - size * 0.5;
    float sd = uArch > 0.5 ? sdArch(c, size * 0.5) : sdBox(c, size * 0.5, uRadius);
    float halo = uHalo * exp(-max(sd, 0.0) / 18.0) * step(0.0, sd);
    float inside = 1.0 - smoothstep(-0.75, 0.75, sd);
    float belowBase = c.y - size.y * 0.5;
    float spill = uArch * step(0.0, sd) * exp(-max(sd, 0.0) / 60.0) * clamp(0.5 + c.y / size.y, 0.0, 1.0);
    float reflAlpha = uArch * step(0.0, belowBase) * step(abs(c.x), size.x * 0.5) * clamp(1.0 - belowBase / (0.35 * size.y), 0.0, 1.0) * 0.28;
    if (inside <= 0.0 && halo < 0.004 && spill < 0.004 && reflAlpha < 0.004) discard;

    vec2 luv = (px - uRect.xy) / size;
    float trans = sin(3.14159 * uMix);
    float mist = clamp(uMist + trans * 0.85, 0.0, 1.0);
    float blur = mist * 5.0 + uBlur * 4.0;
    vec4 pb = paint(uTexB, uDepB, uAspB, luv, size, uZoom + (1.0 - uMix) * 0.4, blur);
    vec3 col; float depth;
    if (uMix < 1.0) {
      vec4 pa = paint(uTexA, uDepA, uAspA, luv, size, uZoom + uMix * 0.7, blur);
      float k = smoothstep(0.3, 0.7, uMix);
      col = mix(pa.rgb, pb.rgb, k);
      depth = mix(pa.a, pb.a, k);
    } else {
      col = pb.rgb;
      depth = pb.a;
    }

    float n = fbm(luv * vec2(2.2, 3.4) + vec2(uTime * 0.018, uTime * 0.004));
    col = mix(col, vec3(dot(col, vec3(0.299, 0.587, 0.114))), mist * 0.6);
    col += uLight * vec3(1.0, 0.96, 0.88) * exp(-dot(luv - (uPointer + 0.5), luv - (uPointer + 0.5)) * 7.0) * (1.0 - mist);

    float star = starField(luv) * step(depth, 0.12);
    float fire = fireflyField(luv) * step(0.3, depth);
    col += (star * vec3(1.0) + fire * vec3(1.0, 0.85, 0.5)) * 0.35 * uDusk * (1.0 - mist) * inside;

    vec4 petal = petalField(luv, size);
    col = mix(col, petal.rgb, petal.a * 0.85 * uPetals * (1.0 - uDusk) * (1.0 - mist) * inside);

    col = mix(col, uFog, 0.07 * n * (1.0 - mist));           // a breath of haze drifting across
    col = mix(col, uFog, smoothstep(0.0, 1.0, mist * (0.75 + 0.5 * n)));

    vec3 graded = (col + 0.03) * vec3(1.05, 1.0, 0.95);
    graded = mix(graded, vec3(dot(graded, vec3(0.299, 0.587, 0.114))), 0.1);
    graded = mix(vec3(0.5), graded, 0.85);
    graded += (hash(px + fract(uTime) * 97.0) - 0.5) * 0.04;
    col = mix(col, graded, uPhoto);

    float alpha = inside * uAlpha;
    vec3 haloColor = vec3(1.0, 0.9, 0.95);
    vec3 spillColor = mix(texture2D(uTexB, vec2(0.5), 10.0).rgb, vec3(1.0), 0.35) * 1.2;
    vec3 reflColor = vec3(0.0);
    if (reflAlpha > 0.001) {
      vec2 rluv = luv;
      rluv.y = 2.0 - luv.y;
      rluv.x += sin(uTime * 1.5 + luv.y * 10.0) * 0.01;
      reflColor = paint(uTexB, uDepB, uAspB, rluv, size, uZoom, 3.0).rgb;
    }
    vec3 outCol = col * alpha + haloColor * halo * (1.0 - inside) + spillColor * spill * (1.0 - inside) + reflColor * reflAlpha;
    gl_FragColor = vec4(outCol, alpha + halo * (1.0 - inside) + spill * (1.0 - inside) + reflAlpha);
  }
`;
