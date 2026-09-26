# Fonts

| Font | Role | Files | License |
| --- | --- | --- | --- |
| Role Model | Display voice: hero, titles, room names (`--font-display`) | `RoleModel-Regular.woff2`, `source/RoleModel-Regular.otf` | Personal and non-profit use only; contact efstudio2@gmail.com for a commercial license |
| Rusilla Serif | All-caps kicker (`--font-caps`) | `RusillaSerif-Regular.woff2`, `source/*.otf` | Demo, personal use only; commercial license from dealitastudio.com |
| Cormorant | Italic accent word, and fallback for punctuation Role Model's demo lacks (`--font-accent`) | `Cormorant-wght*.woff2` | SIL OFL, free for any use |
| Hanken Grotesk | All UI text (`--font-sans`) | `HankenGrotesk-wght.woff2` | SIL OFL, free for any use |

Role Model's demo has letters and numbers but no punctuation, and Rusilla's lacks apostrophes; the CSS stacks fall back to Cormorant for those. In Unity, import the OTFs in `source/` as TextMesh Pro font assets and set Cormorant as each one's fallback. Before return earns money, buy the two commercial licenses or swap both for Cormorant.
