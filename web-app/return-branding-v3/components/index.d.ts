import type * as React from 'react';

export type IconName = 'upload' | 'photos' | 'check' | 'x' | 'alert' | 'clock' | 'lock' | 'people' | 'link' | 'copy' | 'headset' | 'enter' | 'home' | 'mic' | 'micOff' | 'plus' | 'pinch' | 'back' | 'arrowRight' | 'arrowUpRight' | 'play' | 'menu' | 'sun' | 'search' | 'more' | 'mail' | 'refresh' | 'spinner';
export type RoomStatus = 'new' | 'invited' | 'waiting' | 'developing' | 'ready' | 'shared' | 'private' | 'failed';
export interface Person { name: string; here?: boolean; role?: 'owner' | 'visit' | 'add'; note?: string }

export interface IconProps { name: IconName; size?: number; strokeWidth?: number; label?: string; className?: string }
export declare function Icon(props: IconProps): React.ReactElement;

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  /** primary / secondary / ghost / danger on plain surfaces; light / glass / text on imagery */
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger' | 'light' | 'glass' | 'text';
  size?: 'sm' | 'md' | 'lg'; icon?: IconName; iconAfter?: IconName;
  /** Adds the round arrow dot at the end. true = arrowRight. */
  arrow?: boolean | IconName; loading?: boolean; fullWidth?: boolean; href?: string;
}
export declare function Button(props: ButtonProps): React.ReactElement;

export interface FieldProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: React.ReactNode; hint?: React.ReactNode; error?: React.ReactNode; multiline?: boolean;
  onImage?: boolean; onSubmit?: (value: string) => void; submitLabel?: string;
}
export declare function Field(props: FieldProps): React.ReactElement;

export interface NavItem { label: string; href?: string; active?: boolean; onClick?: (e: React.MouseEvent) => void }
export interface GlassNavProps { items?: NavItem[]; brand?: React.ReactNode; brandCenter?: boolean; cta?: React.ReactNode; plain?: boolean; onMenu?: () => void; label?: string; className?: string }
export declare function GlassNav(props: GlassNavProps): React.ReactElement;

export interface HeroFrameProps {
  image?: string; nav?: React.ReactNode; eyebrow?: React.ReactNode; /** All-caps line above the title in Rusilla Serif */ kicker?: React.ReactNode; title?: React.ReactNode; subtitle?: React.ReactNode;
  actions?: React.ReactNode; footer?: React.ReactNode; align?: 'center' | 'bottom-left'; height?: number | string;
  bleed?: boolean; drift?: boolean; parallax?: boolean; label?: string; children?: React.ReactNode; className?: string; style?: React.CSSProperties;
}
export declare function HeroFrame(props: HeroFrameProps): React.ReactElement;
export interface EyebrowProps { badge?: React.ReactNode; children?: React.ReactNode }
export declare function Eyebrow(props: EyebrowProps): React.ReactElement;

export interface StatusTagProps { status: RoomStatus; onImage?: boolean; children?: React.ReactNode; className?: string }
export declare function StatusTag(props: StatusTagProps): React.ReactElement;

export interface RoomCardProps {
  src?: string; title?: string; place?: string; date?: Date | string; photoCount?: number; meta?: string; status?: RoomStatus; waitingFor?: string;
  people?: Person[]; width?: number | string; onOpen?: () => void; onManage?: (e: React.MouseEvent) => void; action?: React.ReactNode; className?: string;
}
export declare function RoomCard(props: RoomCardProps): React.ReactElement;

export interface StepperProps { steps: string[]; current?: number; onImage?: boolean; className?: string }
export declare function Stepper(props: StepperProps): React.ReactElement;

export interface Invitee { name?: string; email: string }
export interface InviteSearchProps {
  results?: Invitee[]; invited?: Invitee[]; onQuery?: (query: string) => void; onInvite?: (person: Invitee) => void; onRemove?: (person: Invitee) => void;
  searching?: boolean; label?: string; placeholder?: string; defaultQuery?: string; className?: string;
}
export declare function InviteSearch(props: InviteSearchProps): React.ReactElement;

export interface Member { name?: string; email?: string; status: 'done' | 'uploading' | 'joined' | 'invited'; count?: number; hasNote?: boolean; progress?: string; sentAgo?: string; isYou?: boolean; isOwner?: boolean; here?: boolean }
export interface MemberListProps { members: Member[]; onResend?: (member: Member) => void; className?: string }
export declare function MemberList(props: MemberListProps): React.ReactElement;

export interface Photo { src: string; name?: string; id?: string }
export interface PhotoDropProps { photos?: Photo[]; max?: number; onFiles?: (files: File[]) => void; onRemove?: (index: number) => void; title?: React.ReactNode; hint?: React.ReactNode; onImage?: boolean; active?: boolean; className?: string }
export declare function PhotoDrop(props: PhotoDropProps): React.ReactElement;

export interface DevelopProgressProps { src?: string; title?: string; steps?: string[]; step?: number; progress?: number; error?: string; actions?: React.ReactNode; className?: string }
export declare function DevelopProgress(props: DevelopProgressProps): React.ReactElement;

export interface PresenceStackProps { people: Person[]; max?: number; size?: 'sm' | 'md' | 'lg'; showLabel?: boolean; onImage?: boolean; className?: string }
export declare function PresenceStack(props: PresenceStackProps): React.ReactElement;

export interface ShareSheetProps {
  title?: string; link?: string; people?: Person[]; onImage?: boolean;
  onInvite?: (value: string) => void; onRoleChange?: (person: Person, role: 'visit' | 'add' | 'remove') => void; onCopy?: () => void; onClose?: () => void; className?: string;
}
export declare function ShareSheet(props: ShareSheetProps): React.ReactElement;

/** VR references: 1 CSS px = 1 dp at panel scale. */
export interface SpatialPanelProps { eyebrow?: React.ReactNode; title?: React.ReactNode; children?: React.ReactNode; actions?: React.ReactNode; width?: number; className?: string }
export declare function SpatialPanel(props: SpatialPanelProps): React.ReactElement;
export interface HandMenuItem { icon: IconName; label: string; onSelect?: () => void; toggle?: boolean; active?: boolean; hover?: boolean }
export interface HandMenuProps { items: HandMenuItem[]; className?: string }
export declare function HandMenu(props: HandMenuProps): React.ReactElement;
export interface NameplateProps { name: string; speaking?: boolean; muted?: boolean; status?: string; here?: boolean; className?: string }
export declare function Nameplate(props: NameplateProps): React.ReactElement;
export interface RoomPortalProps { src?: string; title?: string; people?: number; state?: 'idle' | 'hover' | 'entering'; onEnter?: () => void; className?: string }
export declare function RoomPortal(props: RoomPortalProps): React.ReactElement;

declare global {
  interface Window {
    Return: {
      Icon: typeof Icon; Button: typeof Button; Field: typeof Field; GlassNav: typeof GlassNav; HeroFrame: typeof HeroFrame; Eyebrow: typeof Eyebrow;
      StatusTag: typeof StatusTag; RoomCard: typeof RoomCard; Stepper: typeof Stepper; InviteSearch: typeof InviteSearch; MemberList: typeof MemberList; PhotoDrop: typeof PhotoDrop; DevelopProgress: typeof DevelopProgress;
      PresenceStack: typeof PresenceStack; ShareSheet: typeof ShareSheet; SpatialPanel: typeof SpatialPanel;
      HandMenu: typeof HandMenu; Nameplate: typeof Nameplate; RoomPortal: typeof RoomPortal;
    };
  }
}
