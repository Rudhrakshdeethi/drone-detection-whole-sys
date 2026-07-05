import { ReactNode } from "react";

// Targeting-frame panel: mono index + tracked title + optional right-side readout.
export default function Panel({
  idx,
  title,
  right,
  flush,
  children,
}: {
  idx: string;
  title: string;
  right?: ReactNode;
  flush?: boolean;
  children: ReactNode;
}) {
  return (
    <section className="panel">
      <div className="panel-hd">
        <span className="idx">{idx}</span>
        <h2>{title}</h2>
        {right ? <span className="hd-right">{right}</span> : null}
      </div>
      <div className={`panel-bd${flush ? " flush" : ""}`}>{children}</div>
    </section>
  );
}
