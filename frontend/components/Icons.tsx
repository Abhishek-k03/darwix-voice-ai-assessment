import type { ReactNode } from "react";

type P = { size?: number; strokeWidth?: number; style?: React.CSSProperties };
const base = (children: ReactNode) =>
  function Icon({ size = 22, strokeWidth = 1.8, style }: P) {
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={strokeWidth}
        strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" style={style}>{children}</svg>
    );
  };

export const Mic = base(<><path d="M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3Z" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" /></>);
export const MicOff = base(<><path d="M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3Z" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3M3 3l18 18" /></>);
export const Speaker = base(<><path d="M4 9v6h4l5 4V5L8 9H4Z" /><path d="M16.5 8.5a5 5 0 0 1 0 7" /></>);
export const SpeakerOff = base(<><path d="M4 9v6h4l5 4V5L8 9H4Z" /><path d="M17 9l5 6M22 9l-5 6" /></>);
export const Chat = base(<path d="M4 5h16v11H9l-5 4V5Z" />);
export const Wave = base(<path d="M4 12h2M8 8v8M12 5v14M16 8v8M20 12h-2" />);
export const Book = base(<><path d="M5 4h10a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3V4Z" /><path d="M5 17a3 3 0 0 1 3-3h10" /></>);
export const Radar = base(<><circle cx="12" cy="12" r="3" /><path d="M5.6 5.6a9 9 0 0 0 0 12.8M18.4 5.6a9 9 0 0 1 0 12.8" /></>);
export const Copy = base(<><rect x="9" y="9" width="11" height="11" rx="2" /><path d="M5 15V6a2 2 0 0 1 2-2h9" /></>);
export const Download = base(<path d="M12 4v11m-4-4 4 4 4-4M5 20h14" />);
export const Close = base(<path d="M6 6l12 12M18 6L6 18" />);
export const Send = base(<path d="M12 19V5m-6 6 6-6 6 6" />);
export const Search = base(<><circle cx="11" cy="11" r="6.5" /><path d="m20 20-4.2-4.2" /></>);
export const Arrow = base(<path d="M5 12h14m-6-6 6 6-6 6" />);
export const Chevron = base(<path d="m9 6 6 6-6 6" />);
export const Check = base(<path d="m5 12 5 5 9-10" />);
export const Sparkle = base(<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3Z" />);
export const Thumb = base(<path d="M7 11v9H4v-9h3Zm0 0 4-7a2 2 0 0 1 2 2v3h5a2 2 0 0 1 2 2l-1 6a2 2 0 0 1-2 2H7" />);
export const HangUp = base(<path transform="rotate(135 12 12)" d="M5 4h4l2 5-2.5 1.5a11 11 0 0 0 5 5L15 13l5 2v4a2 2 0 0 1-2 2A16 16 0 0 1 3 6a2 2 0 0 1 2-2Z" />);
