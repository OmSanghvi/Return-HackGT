/* @ds-bundle: {"format":4,"namespace":"Return","components":[{"name":"Icon"},{"name":"Button"},{"name":"Field"},{"name":"GlassNav"},{"name":"HeroFrame"},{"name":"StatusTag"},{"name":"RoomCard"},{"name":"Stepper"},{"name":"InviteSearch"},{"name":"PhotoDrop"},{"name":"MemberList"},{"name":"DevelopProgress"},{"name":"PresenceStack"},{"name":"ShareSheet"},{"name":"SpatialPanel"},{"name":"HandMenu"},{"name":"Nameplate"},{"name":"RoomPortal"}]} */
(function () {
  var React = window.React;
  var h = React.createElement;
  var useState = React.useState, useRef = React.useRef, useEffect = React.useEffect;
  var useId = React.useId || function () { var r = useRef('rt-' + Math.random().toString(36).slice(2, 8)); return r.current; };

  function cx() { return Array.prototype.filter.call(arguments, Boolean).join(' '); }
  function omit(o, keys) { var r = {}; for (var k in o) if (keys.indexOf(k) < 0) r[k] = o[k]; return r; }
  function reduced() { try { return window.matchMedia('(prefers-reduced-motion: reduce)').matches; } catch (e) { return false; } }

  /* ---------- Icon: 24px grid, 1.5 stroke, round caps ---------- */
  var P = {
    upload: ['M12 16V4', 'M7 9l5-5 5 5', 'M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3'],
    photos: ['M4 7h12v12H4z', 'M8 7V4h12v12h-4', 'M4 16l4-4 3 3 2-2 3 3'],
    check: ['M5 12.5l4.5 4.5L19 7.5'],
    x: ['M6 6l12 12', 'M18 6L6 18'],
    alert: ['M12 3.5l9.5 16.5h-19z', 'M12 10v4.5', 'M12 17.3v.2'],
    clock: ['M12 3.5a8.5 8.5 0 1 0 0 17a8.5 8.5 0 1 0 0-17z', 'M12 7.5V12l3 2'],
    lock: ['M6 11h12v9H6z', 'M8.5 11V8a3.5 3.5 0 0 1 7 0v3'],
    people: ['M9 11a3 3 0 1 0 0-6a3 3 0 1 0 0 6z', 'M3.5 19a5.5 5.5 0 0 1 11 0', 'M16 5.3a3 3 0 0 1 0 5.4', 'M17.5 14a5.5 5.5 0 0 1 3 5'],
    link: ['M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1', 'M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1'],
    copy: ['M9 9h11v11H9z', 'M15 9V4H4v11h5'],
    headset: ['M3 9.5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-4l-1.5-2h-3L9 16.5H5a2 2 0 0 1-2-2z'],
    enter: ['M14 4h4a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-4', 'M10 16l4-4-4-4', 'M4 12h10'],
    home: ['M4 11l8-6.5 8 6.5', 'M6 9.5V20h12V9.5'],
    mic: ['M12 3.5a3 3 0 0 0-3 3v5a3 3 0 0 0 6 0v-5a3 3 0 0 0-3-3z', 'M5.5 11.5a6.5 6.5 0 0 0 13 0', 'M12 18v2.5'],
    micOff: ['M4 4l16 16', 'M9 9v2.5a3 3 0 0 0 5 2.2', 'M15 11V6.5a3 3 0 0 0-5.8-1', 'M5.5 11.5a6.5 6.5 0 0 0 10.4 5.2', 'M18.4 13a6.5 6.5 0 0 0 .1-1.5', 'M12 18v2.5'],
    plus: ['M12 5v14', 'M5 12h14'],
    pinch: ['M7 13V6.5a1.5 1.5 0 0 1 3 0V11', 'M10 10.5V5a1.5 1.5 0 0 1 3 0v6', 'M13 10.5a1.5 1.5 0 0 1 3 0V14a6 6 0 0 1-6 6h-.5A5.5 5.5 0 0 1 4 14.5V12a1.5 1.5 0 0 1 3 0'],
    back: ['M9 7l-5 5 5 5', 'M4 12h11a5 5 0 0 1 0 10h-2'],
    arrowRight: ['M5 12h14', 'M13 6l6 6-6 6'],
    arrowUpRight: ['M7 17L17 7', 'M8 7h9v9'],
    play: ['M8 5.5v13l10.5-6.5z'],
    menu: ['M4 8h16', 'M4 16h16'],
    sun: ['M6 14a6 6 0 0 1 12 0z', 'M4 17h16', 'M7 20h10'],
    search: ['M11 4a7 7 0 1 0 0 14a7 7 0 1 0 0-14z', 'M20 20l-4-4'],
    more: ['M12 6v.01', 'M12 12v.01', 'M12 18v.01'],
    mail: ['M4 6h16v12H4z', 'M4 7l8 6 8-6'],
    refresh: ['M20 11a8 8 0 0 0-14.3-4.9L4 8', 'M4 4v4h4', 'M4 13a8 8 0 0 0 14.3 4.9L20 16', 'M20 20v-4h-4'],
    spinner: ['M12 3.5a8.5 8.5 0 1 0 8.5 8.5']
  };
  function Icon(props) {
    var size = props.size || 20, d = P[props.name] || [];
    return h('svg', { className: cx('rt-icon', props.name === 'spinner' && 'rt-spin', props.className), width: size, height: size, viewBox: '0 0 24 24', fill: props.name === 'play' ? 'currentColor' : 'none', stroke: 'currentColor',
      strokeWidth: props.strokeWidth || 1.5, strokeLinecap: 'round', strokeLinejoin: 'round', 'aria-hidden': props.label ? undefined : true, role: props.label ? 'img' : undefined, 'aria-label': props.label },
      d.map(function (p, i) { return h('path', { key: i, d: p }); }));
  }
  Icon.names = Object.keys(P);

  /* ---------- Button ---------- */
  function Button(props) {
    var v = props.variant || 'secondary', s = props.size || 'md';
    var rest = omit(props, ['variant', 'size', 'icon', 'iconAfter', 'arrow', 'loading', 'fullWidth', 'className', 'children', 'href']);
    var tag = props.href ? 'a' : 'button';
    var extra = props.href ? { href: props.href } : { type: props.type || 'button', disabled: props.disabled || props.loading };
    var iconSize = s === 'sm' ? 14 : 18;
    return h(tag, Object.assign({}, rest, extra, {
      className: cx('rt-btn', 'rt-btn-' + v, s !== 'md' && 'rt-btn-' + s, props.arrow && 'rt-btn-arrow', props.fullWidth && 'rt-btn-full', props.className),
      'aria-busy': props.loading || undefined
    }),
      props.loading ? h(Icon, { name: 'spinner', size: iconSize }) : props.icon ? h(Icon, { name: props.icon, size: iconSize }) : null,
      props.children,
      props.iconAfter ? h(Icon, { name: props.iconAfter, size: iconSize }) : null,
      props.arrow ? h('span', { className: 'rt-btn-dot', 'aria-hidden': true }, h(Icon, { name: props.arrow === true ? 'arrowRight' : props.arrow, size: s === 'sm' ? 12 : 16, strokeWidth: 2 })) : null);
  }

  /* ---------- Field ---------- */
  function Field(props) {
    var id = useId();
    var rest = omit(props, ['label', 'hint', 'error', 'multiline', 'className', 'onImage', 'onSubmit', 'submitLabel']);
    var describedBy = ((props.hint && !props.error) ? id + '-h ' : '') + (props.error ? id + '-e' : '');
    var control = h(props.multiline ? 'textarea' : 'input', Object.assign({}, rest, { id: id, className: cx('rt-input', props.onImage && 'rt-input-glass'), 'aria-invalid': props.error ? true : undefined, 'aria-describedby': describedBy.trim() || undefined,
      onKeyDown: function (e) { if (props.onSubmit && e.key === 'Enter' && !props.multiline) props.onSubmit(e.target.value); if (props.onKeyDown) props.onKeyDown(e); } }));
    var inner = props.onSubmit ? h('div', { className: 'rt-inputwrap' }, control,
      h('button', { type: 'button', className: cx('rt-iconbtn', props.onImage && 'rt-iconbtn-light'), 'aria-label': props.submitLabel || 'Submit',
        onClick: function () { var el = document.getElementById(id); props.onSubmit(el ? el.value : ''); } }, h(Icon, { name: 'arrowRight', size: 16, strokeWidth: 2 }))) : control;
    return h('div', { className: cx('rt-field', props.className) },
      props.label && h('label', { className: cx('rt-field-label', props.onImage && 'rt-on-image'), htmlFor: id }, props.label),
      inner,
      props.hint && !props.error && h('div', { className: 'rt-field-hint', id: id + '-h', style: props.onImage ? { color: 'var(--on-image)' } : undefined }, props.hint),
      props.error && h('div', { className: 'rt-field-error', id: id + '-e' }, h(Icon, { name: 'alert', size: 16 }), props.error));
  }

  /* ---------- GlassNav ---------- */
  function GlassNav(props) {
    var items = props.items || [];
    var half = props.brandCenter ? Math.ceil(items.length / 2) : 0;
    function link(it, i) { return h('a', { key: i, href: it.href || '#', 'aria-current': it.active ? 'page' : undefined, onClick: it.onClick }, it.label); }
    var brand = props.brand ? h('span', { className: 'rt-nav-brand' }, props.brand) : null;
    return h('nav', { className: cx('rt-nav', props.plain ? 'rt-nav-plain' : 'rt-glass', props.className), 'aria-label': props.label || 'Main' },
      !props.brandCenter ? brand : null,
      h('span', { className: 'rt-nav-items' },
        props.brandCenter ? [items.slice(0, half).map(link), h(React.Fragment, { key: 'b' }, brand), items.slice(half).map(function (it, i) { return link(it, i + half); })] : items.map(link)),
      props.brandCenter ? h('span', { className: 'rt-nav-menu' }, brand) : null,
      props.cta || null,
      h('button', { type: 'button', className: 'rt-iconbtn rt-iconbtn-light rt-nav-menu', 'aria-label': 'Open menu', onClick: props.onMenu }, h(Icon, { name: 'menu', size: 16, strokeWidth: 2 })));
  }

  /* ---------- HeroFrame ---------- */
  function HeroFrame(props) {
    var ref = useRef(null);
    var align = props.align || 'center';
    useEffect(function () {
      var el = ref.current; if (!el || props.parallax === false || reduced()) return;
      var raf = 0;
      function move(e) { var r = el.getBoundingClientRect(); var x = (e.clientX - r.left) / r.width - .5, y = (e.clientY - r.top) / r.height - .5;
        cancelAnimationFrame(raf); raf = requestAnimationFrame(function () { el.style.setProperty('--rt-px', x.toFixed(3)); el.style.setProperty('--rt-py', y.toFixed(3)); }); }
      function leave() { el.style.setProperty('--rt-px', 0); el.style.setProperty('--rt-py', 0); }
      el.addEventListener('pointermove', move); el.addEventListener('pointerleave', leave);
      return function () { el.removeEventListener('pointermove', move); el.removeEventListener('pointerleave', leave); cancelAnimationFrame(raf); };
    }, [props.parallax]);
    return h('section', { ref: ref, className: cx('rt-hero', 'rt-hero-' + align, props.bleed && 'rt-hero-bleed', props.drift !== false && 'rt-hero-drift', props.className),
      style: Object.assign({}, props.height ? { minHeight: props.height } : null, props.style), 'aria-label': props.label },
      h('div', { className: 'rt-hero-media rt-sky', 'aria-hidden': true },
        h('div', { className: 'rt-drift' }, props.image ? h('img', { className: 'rt-img', src: props.image, alt: '' }) : null),
        h('div', { className: align === 'center' ? 'rt-scrim-center' : 'rt-scrim-bottom' })),
      props.nav ? h('div', { className: 'rt-hero-top' }, props.nav) : null,
      h('div', { className: 'rt-hero-body rt-on-image' },
        props.eyebrow ? h('div', { className: 'rt-reveal' }, props.eyebrow) : null,
        props.kicker ? h('p', { className: 'rt-kicker rt-reveal', style: { margin: 0 } }, props.kicker) : null,
        props.title ? h('h1', { className: 'rt-hero-title rt-reveal rt-reveal-2' }, props.title) : null,
        props.subtitle ? h('p', { className: 'rt-hero-sub rt-reveal rt-reveal-3' }, props.subtitle) : null,
        props.actions ? h('div', { className: 'rt-hero-actions rt-reveal rt-reveal-4' }, props.actions) : null,
        props.children),
      props.footer ? h('div', { className: 'rt-hero-foot rt-on-image' }, props.footer) : null);
  }
  function Eyebrow(props) { return h('span', { className: 'rt-eyebrow rt-glass' }, props.badge ? h('b', null, props.badge) : null, props.children); }

  /* ---------- StatusTag ---------- */
  var STATUS = {
    developing: { icon: 'spinner', word: 'Building' },
    waiting: { icon: 'people', word: 'Waiting' },
    invited: { icon: 'mail', word: 'Invitation' },
    ready: { icon: 'check', word: 'Ready' },
    shared: { icon: 'people', word: 'Shared' },
    'private': { icon: 'lock', word: 'Private' },
    failed: { icon: 'alert', word: "Couldn't build" },
    'new': { icon: 'sun', word: 'New' }
  };
  function StatusTag(props) {
    var key = STATUS[props.status] ? props.status : 'private', s = STATUS[key];
    return h('span', { className: cx('rt-tag', 'rt-tag-' + key, props.onImage && 'rt-glass', props.className) }, h(Icon, { name: s.icon, size: 14, strokeWidth: 2 }), props.children || s.word);
  }

  /* ---------- RoomCard ---------- */
  function fmtDate(d) { if (!d) return ''; var p = String(d).split('-'); var dt = p.length === 3 ? new Date(+p[0], +p[1] - 1, +p[2]) : new Date(d); return isNaN(dt) ? String(d) : dt.toLocaleDateString('en-US', { month: 'long', day: 'numeric', year: 'numeric' }); }
  function RoomCard(props) {
    var st = props.status && props.status !== 'ready' ? props.status : null;
    var word = st === 'waiting' && props.waitingFor ? 'Waiting for ' + props.waitingFor : null;
    var meta = props.meta || [props.place, fmtDate(props.date)].filter(Boolean).join(' · ') || (props.photoCount ? props.photoCount + ' photos' : '');
    return h('div', { className: cx('rt-card', props.status === 'developing' && 'rt-card-developing', props.className), style: props.width ? { width: props.width } : undefined },
      props.src ? h('img', { className: 'rt-img', src: props.src, alt: '' }) : h('span', { className: 'rt-img rt-sky' }),
      h('span', { className: 'rt-scrim-bottom' }),
      h('button', { type: 'button', className: 'rt-card-hit', onClick: props.onOpen, 'aria-label': 'Open ' + (props.title || 'room') + (st ? ', ' + (word || STATUS[st].word) : '') }),
      h('span', { className: 'rt-card-top' }, st ? h(StatusTag, { status: st, onImage: true }, word) : h('span'),
        props.onManage ? h('button', { type: 'button', className: 'rt-iconbtn rt-card-menu', 'aria-label': 'Manage ' + (props.title || 'room'), onClick: props.onManage }, h(Icon, { name: 'more', size: 16, strokeWidth: 2.5 })) : null),
      h('span', { className: 'rt-card-foot' },
        h('span', null, h('span', { className: 'rt-card-title' }, props.title || 'Untitled room'), meta ? h('span', { className: 'rt-card-meta' }, meta) : null),
        props.people && props.people.length ? h(PresenceStack, { people: props.people, max: 3, size: 'sm', onImage: true }) : null),
      props.action ? h('span', { className: 'rt-card-action' }, props.action) : null);
  }

  /* ---------- PresenceStack ---------- */
  function initials(n) { return (n || '?').split(/\s+/).map(function (w) { return w[0]; }).join('').slice(0, 2).toUpperCase(); }
  function PresenceStack(props) {
    var people = props.people || [], max = props.max || 4;
    var shown = people.slice(0, max), extra = people.length - shown.length;
    var here = people.filter(function (p) { return p.here; });
    var sz = props.size === 'sm' ? 'rt-avatar-sm' : props.size === 'lg' ? 'rt-avatar-lg' : null;
    return h('span', { className: cx('rt-stack', props.onImage && 'rt-stack-onimage', props.className), role: 'group', 'aria-label': people.length + ' people' + (here.length ? ', ' + here.length + ' here now' : '') },
      shown.map(function (p, i) { return h('span', { key: i, className: cx('rt-avatar', sz, p.here && 'rt-avatar-here'), title: p.name + (p.here ? ' (here now)' : '') }, initials(p.name)); }),
      extra > 0 ? h('span', { className: cx('rt-avatar', 'rt-avatar-more', sz) }, '+' + extra) : null,
      props.showLabel && here.length ? h('span', { className: 'rt-stack-label' }, here.length + ' here now') : null);
  }

  /* ---------- PhotoDrop ---------- */
  function PhotoDrop(props) {
    var _a = useState(false), over = _a[0], setOver = _a[1];
    var input = useRef(null);
    var photos = props.photos || [], max = props.max || 12, active = over || props.active;
    function take(list) { var files = Array.prototype.slice.call(list || []).filter(function (f) { return /^image\//.test(f.type); }); if (files.length && props.onFiles) props.onFiles(files.slice(0, Math.max(0, max - photos.length))); }
    function open() { if (input.current) input.current.click(); }
    return h('div', { className: props.className },
      h('div', { className: cx('rt-drop', props.onImage && 'rt-glass-strong', active && 'rt-drop-active'), role: 'button', tabIndex: 0, 'aria-label': 'Add photos. Drop images here or press Enter to choose files.',
        onClick: open, onKeyDown: function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open(); } },
        onDragOver: function (e) { e.preventDefault(); if (!over) setOver(true); }, onDragLeave: function () { setOver(false); },
        onDrop: function (e) { e.preventDefault(); setOver(false); take(e.dataTransfer.files); } },
        h('span', { className: 'rt-drop-icon' }, h(Icon, { name: active ? 'photos' : 'upload', size: 24 })),
        h('span', { className: 'rt-drop-title' }, active ? h(React.Fragment, null, 'Let ', h('em', null, 'go')) : (props.title || h(React.Fragment, null, 'Bring a ', h('em', null, 'moment'), ' back'))),
        h('span', { className: 'rt-drop-hint' }, props.hint || 'Drop 1 to ' + max + ' photos of the same place. More angles build a fuller world.'),
        h('input', { ref: input, type: 'file', accept: 'image/*', multiple: true, hidden: true, onChange: function (e) { take(e.target.files); e.target.value = ''; } })),
      photos.length ? h('div', { className: 'rt-strip', role: 'list', 'aria-label': 'Selected photos' }, photos.map(function (p, i) {
        return h('div', { key: p.id || i, role: 'listitem', className: cx('rt-thumb', i === 0 && 'rt-thumb-cover') },
          h('img', { className: 'rt-img', src: p.src, alt: p.name || 'Photo ' + (i + 1) }),
          props.onRemove ? h('button', { type: 'button', className: 'rt-iconbtn', 'aria-label': 'Remove ' + (p.name || 'photo ' + (i + 1)), onClick: function () { props.onRemove(i); } }, h(Icon, { name: 'x', size: 14, strokeWidth: 2 })) : null);
      })) : null,
      photos.length ? h('div', { className: 'rt-drop-count' }, h('span', null, photos.length + ' of ' + max + ' photos'), h('span', null, 'The first photo is the cover')) : null);
  }

  /* ---------- DevelopProgress: the scene resolves out of the mist ---------- */
  var DEFAULT_STEPS = ['Reading your photos', 'Estimating depth', 'Building the world', 'Setting the light'];
  function DevelopProgress(props) {
    var steps = props.steps || DEFAULT_STEPS, cur = props.step || 0, failed = !!props.error;
    var pct = Math.max(0, Math.min(1, props.progress != null ? props.progress : cur / steps.length));
    var f = 'blur(' + (18 - 18 * pct).toFixed(1) + 'px) saturate(' + (0.35 + 0.65 * pct).toFixed(2) + ') brightness(' + (1.25 - 0.25 * pct).toFixed(2) + ')';
    return h('section', { className: cx('rt-develop', props.className), 'aria-live': 'polite' },
      h('div', { className: 'rt-develop-photo' },
        props.src ? h('img', { className: 'rt-img', src: props.src, alt: '', style: { filter: failed ? 'grayscale(1) blur(8px)' : f } }) : null,
        h('div', { className: 'rt-develop-mist', style: { opacity: failed ? 0.5 : (1 - pct) * 0.85 } })),
      h('div', null,
        h('h3', { className: 'rt-develop-title' }, failed ? h(React.Fragment, null, 'Still in the ', h('em', null, 'fog')) : pct >= 1 ? h(React.Fragment, null, 'Ready to ', h('em', null, 'return')) : h(React.Fragment, null, 'Coming into ', h('em', null, 'focus'))),
        h('p', { className: 'rt-develop-sub' }, failed ? props.error : pct >= 1 ? 'Put on your headset. It\'s waiting in your rooms.' : (props.title ? props.title + ' · ' : '') + 'About a minute. You can leave this page.'),
        h('div', { className: 'rt-bar', role: 'progressbar', 'aria-valuemin': 0, 'aria-valuemax': 100, 'aria-valuenow': Math.round(pct * 100), 'aria-label': 'Building the world' },
          h('i', { style: { width: pct * 100 + '%', background: failed ? 'var(--danger)' : pct >= 1 ? 'var(--success)' : undefined } })),
        h('ol', { className: 'rt-steps' }, steps.map(function (s, i) {
          var state = failed && i === cur ? 'failed' : i < cur || pct >= 1 ? 'done' : i === cur ? 'now' : 'todo';
          return h('li', { key: i, className: cx('rt-step', 'rt-step-' + state) }, h(Icon, { name: state === 'done' ? 'check' : state === 'now' ? 'spinner' : state === 'failed' ? 'alert' : 'clock', size: 16, strokeWidth: 2 }), s);
        })),
        props.actions ? h('div', { style: { display: 'flex', gap: 'var(--space-2)', marginTop: 'var(--space-5)', flexWrap: 'wrap' } }, props.actions) : null));
  }

  /* ---------- ShareSheet ---------- */
  function ShareSheet(props) {
    var _a = useState(false), copied = _a[0], setCopied = _a[1];
    var people = props.people || [];
    function copy() { try { if (navigator.clipboard) navigator.clipboard.writeText(props.link); } catch (e) {} setCopied(true); setTimeout(function () { setCopied(false); }, 1600); if (props.onCopy) props.onCopy(); }
    return h('section', { className: cx('rt-share', props.onImage && 'rt-glass-strong', props.className), role: 'dialog', 'aria-label': 'Share ' + (props.title || 'room') },
      h('div', { className: 'rt-share-head' },
        h('div', null, h('h2', { className: 'rt-share-title' }, 'Who can ', h('em', null, 'return'), ' here'), props.title ? h('p', { className: 'rt-share-sub' }, props.title) : null),
        props.onClose ? h('button', { type: 'button', className: 'rt-iconbtn rt-iconbtn-quiet', 'aria-label': 'Close', onClick: props.onClose }, h(Icon, { name: 'x', size: 16, strokeWidth: 2 })) : null),
      h(Field, { label: 'Invite by name or email', placeholder: 'Mom, sam@school.edu', onSubmit: function (v) { if (v && props.onInvite) props.onInvite(v); }, submitLabel: 'Invite' }),
      people.length ? h('div', null, h('p', { className: 'rt-section-label' }, 'People with access'),
        h('ul', { className: 'rt-people' }, people.map(function (p, i) {
          return h('li', { key: i, className: 'rt-person' },
            h('span', { className: cx('rt-avatar', p.here && 'rt-avatar-here') }, initials(p.name)),
            h('span', { className: 'rt-person-name' }, p.name, h('small', { className: p.here ? 'rt-here' : undefined }, p.here ? 'Here now, in the headset' : p.role === 'owner' ? 'Made this room' : p.note || 'Invited')),
            p.role === 'owner' ? h('span', { className: 'rt-field-hint' }, 'Owner') :
              h('select', { className: 'rt-select', defaultValue: p.role || 'visit', 'aria-label': 'Access for ' + p.name, onChange: function (e) { if (props.onRoleChange) props.onRoleChange(p, e.target.value); } },
                h('option', { value: 'visit' }, 'Can visit'), h('option', { value: 'add' }, 'Can add photos'), h('option', { value: 'remove' }, 'Remove')));
        }))) : null,
      props.link ? h('div', { style: { display: 'flex', gap: 'var(--space-2)', alignItems: 'center', justifyContent: 'space-between' } },
        h('span', { className: 'rt-field-hint', style: { display: 'flex', gap: 'var(--space-1)', alignItems: 'center' } }, h(Icon, { name: 'link', size: 16 }), 'Anyone with the link can visit'),
        h(Button, { variant: 'secondary', size: 'sm', icon: copied ? 'check' : 'copy', onClick: copy }, copied ? 'Copied' : 'Copy link')) : null);
  }

  /* ---------- Stepper ---------- */
  function Stepper(props) {
    var steps = props.steps || [], cur = props.current || 0;
    return h('ol', { className: cx('rt-stepper', props.onImage && 'rt-on-image', props.className), 'aria-label': 'Progress' }, steps.map(function (s, i) {
      return h('li', { key: i, className: cx('rt-stepper-item', i < cur && 'rt-stepper-done', i === cur && 'rt-stepper-now'), 'aria-current': i === cur ? 'step' : undefined },
        h('span', { className: 'rt-stepper-dot' }, i < cur ? h(Icon, { name: 'check', size: 12, strokeWidth: 2.5 }) : i + 1), s);
    }));
  }

  /* ---------- InviteSearch ---------- */
  var EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  function InviteSearch(props) {
    var _q = useState(props.defaultQuery || ''), q = _q[0], setQ = _q[1];
    var results = props.results || [], invited = props.invited || [];
    var isInvited = function (email) { return invited.some(function (p) { return p.email === email; }); };
    var raw = q.trim(), showRaw = EMAIL.test(raw) && !results.some(function (r) { return r.email === raw; }) && !isInvited(raw);
    function change(e) { setQ(e.target.value); if (props.onQuery) props.onQuery(e.target.value); }
    function row(p, i, isNew) {
      var done = isInvited(p.email);
      return h('li', { key: p.email || i, className: 'rt-result' },
        h('span', { className: 'rt-avatar' }, isNew ? h(Icon, { name: 'mail', size: 14 }) : initials(p.name || p.email)),
        h('span', { className: 'rt-person-name' }, isNew ? 'Invite ' + p.email : p.name, h('small', null, isNew ? 'Not on return yet. We\'ll email them an invite.' : p.email)),
        done ? h('span', { className: 'rt-result-done' }, h(Icon, { name: 'check', size: 14, strokeWidth: 2.5 }), 'Invited') :
          h(Button, { size: 'sm', variant: 'secondary', icon: 'plus', onClick: function () { if (props.onInvite) props.onInvite(p); setQ(''); } }, 'Invite'));
    }
    return h('div', { className: cx('rt-invite', props.className) },
      h('div', { className: 'rt-field' },
        h('label', { className: 'rt-field-label', htmlFor: 'rt-invite-q' }, props.label || 'Invite people by email'),
        h('div', { className: 'rt-inputwrap rt-inputwrap-lead' }, h('span', { className: 'rt-input-lead', 'aria-hidden': true }, h(Icon, { name: 'search', size: 18 })),
          h('input', { id: 'rt-invite-q', className: 'rt-input', type: 'search', value: q, onChange: change, placeholder: props.placeholder || 'Search by name or email', autoComplete: 'off' }))),
      q && (results.length || showRaw) ? h('ul', { className: 'rt-results', role: 'listbox', 'aria-label': 'Search results' },
        results.map(function (p, i) { return row(p, i, false); }), showRaw ? row({ email: raw }, 'raw', true) : null) :
        q && props.searching ? h('p', { className: 'rt-field-hint', style: { margin: 0 } }, 'Searching…') :
        q ? h('p', { className: 'rt-field-hint', style: { margin: 0 } }, 'No one found. Type their full email to invite them.') : null,
      invited.length ? h('div', null, h('p', { className: 'rt-section-label' }, 'Invited (' + invited.length + ')'),
        h('ul', { className: 'rt-chips' }, invited.map(function (p, i) {
          return h('li', { key: p.email || i, className: 'rt-chip' }, h('span', { className: 'rt-avatar rt-avatar-sm' }, initials(p.name || p.email)), p.name || p.email,
            props.onRemove ? h('button', { type: 'button', className: 'rt-chip-x', 'aria-label': 'Remove ' + (p.name || p.email), onClick: function () { props.onRemove(p); } }, h(Icon, { name: 'x', size: 12, strokeWidth: 2.5 })) : null);
        }))) : null);
  }

  /* ---------- MemberList: who has added their photos ---------- */
  var MEMBER = {
    done: { icon: 'check', cls: 'rt-m-done' },
    uploading: { icon: 'spinner', cls: 'rt-m-uploading' },
    joined: { icon: 'clock', cls: 'rt-m-joined' },
    invited: { icon: 'mail', cls: 'rt-m-invited' }
  };
  function memberLine(m) {
    if (m.status === 'done') return 'Added ' + (m.count || 0) + ' photo' + (m.count === 1 ? '' : 's') + (m.hasNote ? ' and a note' : '');
    if (m.status === 'uploading') return 'Uploading' + (m.progress ? ' ' + m.progress : '');
    if (m.status === 'joined') return 'Joined, hasn\'t added photos yet';
    return 'Invite sent' + (m.sentAgo ? ' ' + m.sentAgo : '');
  }
  function MemberList(props) {
    var members = props.members || [];
    return h('ul', { className: cx('rt-members', props.className), 'aria-label': 'People in this room' }, members.map(function (m, i) {
      var s = MEMBER[m.status] || MEMBER.invited;
      return h('li', { key: m.email || i, className: cx('rt-member', s.cls) },
        h('span', { className: cx('rt-avatar', m.here && 'rt-avatar-here') }, initials(m.name || m.email)),
        h('span', { className: 'rt-person-name' }, (m.name || m.email) + (m.isYou ? ' (you)' : ''), h('small', null, h(Icon, { name: s.icon, size: 13, strokeWidth: 2.25 }), memberLine(m))),
        m.status === 'invited' && props.onResend ? h(Button, { size: 'sm', variant: 'ghost', icon: 'refresh', onClick: function () { props.onResend(m); } }, 'Resend') :
          m.isOwner ? h('span', { className: 'rt-field-hint' }, 'Owner') : null);
    }));
  }

  /* ---------- Spatial ---------- */
  function SpatialPanel(props) {
    return h('section', { className: cx('rt-panel', 'rt-glass-strong', props.className), style: props.width ? { '--rt-panel-w': props.width + 'px' } : undefined, 'aria-label': typeof props.title === 'string' ? props.title : undefined },
      props.eyebrow || props.title ? h('header', null, props.eyebrow ? h('p', { className: 'rt-panel-eyebrow' }, props.eyebrow) : null, props.title ? h('h2', { className: 'rt-panel-title' }, props.title) : null) : null,
      props.children ? h('div', { className: 'rt-panel-body' }, props.children) : null,
      props.actions ? h('footer', { className: 'rt-panel-actions' }, props.actions) : null);
  }
  function HandMenu(props) {
    return h('nav', { className: cx('rt-hm', 'rt-glass', props.className), 'aria-label': 'Hand menu' }, (props.items || []).map(function (it, i) {
      return h('button', { key: i, type: 'button', className: 'rt-hm-btn', 'aria-pressed': it.toggle ? !!it.active : undefined, 'data-hover': it.hover ? 'true' : undefined, onClick: it.onSelect },
        h('span', { className: 'rt-hm-ico' }, h(Icon, { name: it.icon, size: 22 })), it.label);
    }));
  }
  function Nameplate(props) {
    return h('div', { className: cx('rt-plate', props.here !== false && 'rt-plate-here', props.speaking && 'rt-plate-speaking', props.className), role: 'note', 'aria-label': props.name + (props.speaking ? ', speaking' : '') + (props.muted ? ', muted' : '') },
      h('span', { className: 'rt-plate-pill rt-glass' }, h('span', { className: 'rt-avatar' }, initials(props.name)), props.name,
        props.muted ? h(Icon, { name: 'micOff', size: 20 }) : h('span', { className: 'rt-wave', 'aria-hidden': true }, h('i'), h('i'), h('i'))),
      props.status ? h('span', { className: 'rt-plate-sub' }, props.status) : null);
  }
  function RoomPortal(props) {
    var state = props.state || 'idle';
    return h('button', { type: 'button', className: cx('rt-portal', 'rt-portal-' + state, props.className), onClick: props.onEnter, 'aria-label': 'Step into ' + (props.title || 'room') },
      h('span', { className: 'rt-portal-window' }, props.src ? h('img', { className: 'rt-img', src: props.src, alt: '' }) : null),
      h('span', { className: 'rt-portal-caption' },
        h('p', { className: 'rt-portal-title' }, props.title),
        h('p', { className: 'rt-portal-hint' }, h(Icon, { name: 'pinch', size: 18 }), state === 'entering' ? 'Stepping in' : state === 'hover' ? 'Pinch to step inside' : (props.people ? props.people + ' people have been here' : 'Look to select'))));
  }

  var api = { Icon: Icon, Button: Button, Field: Field, GlassNav: GlassNav, HeroFrame: HeroFrame, Eyebrow: Eyebrow, StatusTag: StatusTag, RoomCard: RoomCard, PhotoDrop: PhotoDrop,
    DevelopProgress: DevelopProgress, PresenceStack: PresenceStack, ShareSheet: ShareSheet, Stepper: Stepper, InviteSearch: InviteSearch, MemberList: MemberList, SpatialPanel: SpatialPanel, HandMenu: HandMenu, Nameplate: Nameplate, RoomPortal: RoomPortal };
  window.Return = Object.assign(window.Return || {}, api);
})();
