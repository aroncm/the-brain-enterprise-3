import type { CSSProperties, ReactNode } from "react";

// Public, no-login pages: landing (root, signed-out visitors), terms, privacy.
// These exist so carrier and partner reviewers can see who operates the
// service and how the text-alert program works without an account
// (Twilio toll-free rejection 30491). Styling is self-contained inline
// (no styles.css classes); brand mark and accent match the login page.
// House rules: plain English, no betting references, "trigger" terminology.

const ACCENT = "#2ec4a0";
const INK = "#e8eaf0";
const MUTED = "rgba(232, 234, 240, 0.68)";
const SURFACE = "#10141c";
const EDGE = "rgba(255,255,255,0.08)";

const ui = {
  page: {
    minHeight: "100vh",
    background: "#0a0d13",
    color: INK,
    fontFamily: "'Helvetica Neue', Helvetica, Arial, sans-serif",
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    padding: "0 20px 56px",
  } as CSSProperties,
  inner: { width: "min(880px, 100%)" } as CSSProperties,
  nav: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    padding: "26px 0 10px",
  } as CSSProperties,
  signIn: {
    background: ACCENT,
    border: "none",
    borderRadius: 8,
    color: "#06251d",
    padding: "10px 22px",
    fontSize: 14,
    fontWeight: 700,
    cursor: "pointer",
    textDecoration: "none",
  } as CSSProperties,
  eyebrow: {
    fontSize: 11,
    fontWeight: 600,
    letterSpacing: "0.28em",
    textTransform: "uppercase",
    color: ACCENT,
    margin: "72px 0 14px",
  } as CSSProperties,
  h1: {
    fontSize: "clamp(30px, 5vw, 44px)",
    fontWeight: 700,
    lineHeight: 1.15,
    letterSpacing: "-0.01em",
    margin: "0 0 16px",
  } as CSSProperties,
  lede: {
    fontSize: 18,
    lineHeight: 1.6,
    color: MUTED,
    maxWidth: 620,
    margin: "0 0 48px",
  } as CSSProperties,
  cardRow: {
    display: "flex",
    gap: 16,
    flexWrap: "wrap",
    margin: "0 0 56px",
  } as CSSProperties,
  card: {
    flex: "1 1 240px",
    background: SURFACE,
    border: `1px solid ${EDGE}`,
    borderRadius: 12,
    padding: "22px 22px 20px",
  } as CSSProperties,
  cardTitle: {
    fontSize: 12,
    fontWeight: 700,
    letterSpacing: "0.18em",
    textTransform: "uppercase",
    color: ACCENT,
    margin: "0 0 10px",
  } as CSSProperties,
  cardBody: { fontSize: 14.5, lineHeight: 1.6, color: MUTED, margin: 0 } as CSSProperties,
  band: {
    background: SURFACE,
    border: `1px solid ${EDGE}`,
    borderLeft: `3px solid ${ACCENT}`,
    borderRadius: 12,
    padding: "24px 26px",
    margin: "0 0 48px",
  } as CSSProperties,
  h2: { fontSize: 20, fontWeight: 700, margin: "0 0 10px" } as CSSProperties,
  p: { fontSize: 15, lineHeight: 1.65, color: MUTED, margin: "0 0 12px" } as CSSProperties,
  fine: { fontSize: 13.5, lineHeight: 1.6, color: MUTED, margin: 0 } as CSSProperties,
  footer: {
    marginTop: 56,
    paddingTop: 20,
    borderTop: `1px solid ${EDGE}`,
    fontSize: 13,
    color: MUTED,
    lineHeight: 1.8,
  } as CSSProperties,
  link: { color: ACCENT, textDecoration: "none" } as CSSProperties,
  // content pages (terms / privacy)
  docTitle: { fontSize: 30, fontWeight: 700, margin: "48px 0 6px" } as CSSProperties,
  docDate: { fontSize: 13, color: MUTED, margin: "0 0 28px" } as CSSProperties,
  docH2: { fontSize: 16, fontWeight: 700, margin: "26px 0 8px" } as CSSProperties,
};

function BrandMark({ height = 34 }: { height?: number }) {
  return (
    <svg
      viewBox="0 0 565 115"
      height={height}
      xmlns="http://www.w3.org/2000/svg"
      role="img"
      aria-label="Baseball brAIn"
    >
      <text x="20" y="82" fontFamily="'Helvetica Neue',Helvetica,Arial,sans-serif" fontSize="36" fontWeight="300" letterSpacing="6" fill="#FFFFFF">BASEBALL</text>
      <text x="322" y="82" fontFamily="'Helvetica Neue',Helvetica,Arial,sans-serif" fontSize="84" fontWeight="700" letterSpacing="-1" fill="#FFFFFF" fillOpacity="0.7">
        <tspan fillOpacity="0.7">br</tspan>
        <tspan fill={ACCENT} fillOpacity="1">AI</tspan>
        <tspan fillOpacity="0.7">n</tspan>
      </text>
      <polygon points="277,17 312,52 277,87 242,52" fill="none" stroke="#FFFFFF" strokeWidth="2.5" strokeLinejoin="miter" />
      <line x1="269" y1="52" x2="285" y2="52" stroke={ACCENT} strokeWidth="1.8" strokeLinecap="round" />
      <line x1="277" y1="44" x2="277" y2="60" stroke={ACCENT} strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}

function Shell({ children, onSignIn }: { children: ReactNode; onSignIn?: () => void }) {
  return (
    <div style={ui.page}>
      <div style={ui.inner}>
        <nav style={ui.nav}>
          <a href="/" aria-label="Baseball brAIn home" style={{ display: "inline-flex" }}>
            <BrandMark />
          </a>
          {onSignIn ? (
            <button type="button" style={ui.signIn} onClick={onSignIn}>
              Sign in
            </button>
          ) : (
            <a href="/?signin=1" style={ui.signIn}>
              Sign in
            </a>
          )}
        </nav>
        {children}
        <footer style={ui.footer}>
          <span>
            Baseball brAIn is the trade name of Clearmeadow Partners LLC · Delray Beach, FL
          </span>
          <br />
          <a href="/?page=terms" style={ui.link}>
            Terms of Service
          </a>
          <span style={{ margin: "0 10px", opacity: 0.5 }}>·</span>
          <a href="/?page=privacy" style={ui.link}>
            Privacy Policy
          </a>
        </footer>
      </div>
    </div>
  );
}

function Landing({ onSignIn }: { onSignIn: () => void }) {
  return (
    <Shell onSignIn={onSignIn}>
      <p style={ui.eyebrow}>Advanced Baseball Intelligence</p>
      <h1 style={ui.h1}>
        The pitching change,
        <br />
        measured in real time.
      </h1>
      <p style={ui.lede}>
        Baseball brAIn scores every pitch of every Major League game, weighs the starter
        against the bullpen behind him, and marks the moment a pitching change is
        warranted. Club staff see it live, in replay, and in their inbox.
      </p>

      <div style={ui.cardRow}>
        <div style={ui.card}>
          <p style={ui.cardTitle}>Live Triggers</p>
          <p style={ui.cardBody}>
            During games, the model tracks each starter pitch by pitch and escalates
            through Watch, Prep, and Pull Now as his outlook changes.
          </p>
        </div>
        <div style={ui.card}>
          <p style={ui.cardTitle}>Game Replays</p>
          <p style={ui.cardBody}>
            A pitch-by-pitch review of every game: how the model's read developed,
            where the trigger fired, and what followed.
          </p>
        </div>
        <div style={ui.card}>
          <p style={ui.cardTitle}>Game Briefings</p>
          <p style={ui.cardBody}>
            A morning email covering each game's pitching decisions and the moments
            that mattered.
          </p>
        </div>
      </div>

      <div style={ui.band}>
        <h2 style={ui.h2}>Text alerts</h2>
        <p style={ui.p}>
          Account holders can opt in to a text message when the model reaches a trigger
          in their club's live games. Enrollment is opt-in only, in account settings or
          by written consent recorded by an administrator.
        </p>
        <p style={ui.fine}>
          Message frequency varies with the game schedule. Message and data rates may
          apply. Reply STOP to opt out, HELP for help. See our{" "}
          <a href="/?page=terms" style={ui.link}>
            Terms of Service
          </a>{" "}
          and{" "}
          <a href="/?page=privacy" style={ui.link}>
            Privacy Policy
          </a>
          .
        </p>
      </div>

      <p style={{ ...ui.p, marginBottom: 0 }}>
        Baseball brAIn is available by invitation to Major League Baseball club
        personnel.
      </p>
    </Shell>
  );
}

function Terms() {
  return (
    <Shell>
      <h1 style={ui.docTitle}>Terms of Service</h1>
      <p style={ui.docDate}>Effective August 21, 2026</p>
      <p style={ui.p}>
        Baseball brAIn (the "Service") is operated by Clearmeadow Partners LLC
        ("we", "us"). By using the Service you agree to these terms.
      </p>
      <h2 style={ui.docH2}>1. Accounts and access</h2>
      <p style={ui.p}>
        Accounts are created by invitation for authorized Major League Baseball club
        personnel and our own staff. You are responsible for keeping your credentials
        confidential and for activity under your account. We may suspend accounts that
        misuse the Service or share access outside their organization.
      </p>
      <h2 style={ui.docH2}>2. The analytics</h2>
      <p style={ui.p}>
        The Service provides analytical models and decision support. It does not make
        decisions for you, and we do not guarantee any outcome from acting or not acting
        on a model output. The Service is provided as is, without warranties of any kind.
      </p>
      <h2 style={ui.docH2}>3. Text alerts</h2>
      <p style={ui.p}>
        Users may opt in to receive automated text alerts when the model reaches a
        pitching-change trigger in their club's live games. Consent is collected in
        account settings or as written consent recorded by an administrator. Message
        frequency varies with the game schedule. Message and data rates may apply.
        Reply STOP to any message to opt out, or HELP for help. Opting out of texts
        does not affect your account or email briefings. Carriers are not liable for
        delayed or undelivered messages.
      </p>
      <h2 style={ui.docH2}>4. Intellectual property</h2>
      <p style={ui.p}>
        The Service, its models, and its outputs are the property of Clearmeadow
        Partners LLC. Club data access is scoped to your organization under your
        organization's agreement with us.
      </p>
      <h2 style={ui.docH2}>5. Contact</h2>
      <p style={ui.p}>
        Questions about these terms:{" "}
        <a href="mailto:aroncm@gmail.com" style={ui.link}>
          aroncm@gmail.com
        </a>
        , or Clearmeadow Partners LLC, 16768 Matisse Drive, Delray Beach, FL 33446.
      </p>
    </Shell>
  );
}

function Privacy() {
  return (
    <Shell>
      <h1 style={ui.docTitle}>Privacy Policy</h1>
      <p style={ui.docDate}>Effective August 21, 2026</p>
      <h2 style={ui.docH2}>What we collect</h2>
      <p style={ui.p}>
        Account information (name, work email, role, club affiliation), a mobile phone
        number if you opt in to text alerts, and basic usage information needed to
        operate and secure the Service. The baseball data we analyze is game data, not
        personal data about you.
      </p>
      <h2 style={ui.docH2}>How we use it</h2>
      <p style={ui.p}>
        To provide the Service: signing you in, scoping your access to your club,
        sending email briefings you are enrolled in, and sending text alerts you have
        opted in to. We do not sell personal information.
      </p>
      <h2 style={ui.docH2}>Text messaging</h2>
      <p style={ui.p}>
        Phone numbers are collected only through opt-in, and each opt-in is recorded
        with a timestamp and who recorded it. No mobile information will be shared with
        third parties or affiliates for marketing or promotional purposes. Text
        messaging originator opt-in data and consent will not be shared with any third
        parties, except our messaging delivery provider solely to deliver the messages.
        Reply STOP to opt out at any time.
      </p>
      <h2 style={ui.docH2}>Retention and security</h2>
      <p style={ui.p}>
        We keep account and consent records while your account is active and as needed
        to meet legal and carrier requirements. Access to personal information is
        limited to staff who need it to operate the Service.
      </p>
      <h2 style={ui.docH2}>Contact</h2>
      <p style={ui.p}>
        Privacy questions:{" "}
        <a href="mailto:aroncm@gmail.com" style={ui.link}>
          aroncm@gmail.com
        </a>
        , or Clearmeadow Partners LLC, 16768 Matisse Drive, Delray Beach, FL 33446.
      </p>
    </Shell>
  );
}

export function PublicSite({
  page,
  onSignIn,
}: {
  page: "landing" | "terms" | "privacy";
  onSignIn: () => void;
}) {
  if (page === "terms") return <Terms />;
  if (page === "privacy") return <Privacy />;
  return <Landing onSignIn={onSignIn} />;
}
