// Clerk appearance for return. Pass to <ClerkProvider appearance={returnAppearance(theme)}> or to <SignIn /> / <SignUp />.
// Values mirror tokens.json (day and dusk). Load tokens.css and components/bundle.css on the page so the class hooks below apply.
// Variable names follow Clerk's current variables prop (colorForeground, colorInput, colorMutedForeground, colorPrimaryForeground, spacing).
// Element keys: verify against Clerk's element inspector for your Clerk version before relying on them.

type Theme = 'day' | 'dusk';

const palette = {
  day:  { primary: '#141a2b', onPrimary: '#ffffff', fg: '#141a2b', muted: '#4a5166', bg: '#f7f5f1', input: '#ffffff', inputFg: '#141a2b', border: '#7d786b', danger: '#b23a33', success: '#276c42', ring: '#2f5fa8', neutral: '#141a2b', link: '#2f5fa8' },
  dusk: { primary: '#f4f1ea', onPrimary: '#141a2b', fg: '#eef0fa', muted: '#b3b8d4', bg: '#19203d', input: '#11172d', inputFg: '#eef0fa', border: '#6f78a8', danger: '#ff9d92', success: '#8fd9a8', ring: '#b9d3ff', neutral: '#eef0fa', link: '#9cc2ff' },
} as const;

export function returnAppearance(theme: Theme = 'day') {
  const c = palette[theme];
  return {
    variables: {
      colorPrimary: c.primary,
      colorPrimaryForeground: c.onPrimary,
      colorForeground: c.fg,
      colorMutedForeground: c.muted,
      colorBackground: c.bg,
      colorInput: c.input,
      colorInputForeground: c.inputFg,
      colorBorder: c.border,
      colorNeutral: c.neutral,
      colorDanger: c.danger,
      colorSuccess: c.success,
      colorRing: c.ring,
      borderRadius: '16px',
      fontFamily: '"Hanken Grotesk", system-ui, sans-serif',
      fontFamilyButtons: '"Hanken Grotesk", system-ui, sans-serif',
      fontSize: '15px',
      spacing: '1rem',
    },
    elements: {
      // Frosted card over the cloud imagery (glass-strong)
      card: 'rt-glass-strong',
      cardBox: { borderRadius: '24px', boxShadow: 'var(--shadow-float)' },
      headerTitle: { fontFamily: '"Role Model", Cormorant, Georgia, serif', fontWeight: 400, fontSize: '40px', lineHeight: '44px', letterSpacing: '-0.01em' },
      headerSubtitle: { color: c.muted },
      // Pills everywhere
      formButtonPrimary: { borderRadius: '999px', height: '44px', fontWeight: 500, textTransform: 'none' },
      socialButtonsBlockButton: { borderRadius: '999px', height: '44px' },
      formFieldInput: { borderRadius: '999px', height: '44px', paddingInline: '20px' },
      footerActionLink: { color: c.link },
    },
  };
}
