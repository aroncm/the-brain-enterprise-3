import type { CSSProperties, ReactNode } from "react";

// Public, no-login pages: landing (root, signed-out visitors), terms, privacy.
// These exist so carrier and partner reviewers can see who operates the
// service and how the text-alert program works without an account
// (Twilio toll-free rejection 30491: "Website Is Password Protected or
// Requires Login"). Styling is self-contained inline (no styles.css classes).
// House rules: plain English, no betting references, "trigger" terminology.

const ui = {
  page: {
    minHeight: "100vh",
    background: "#0a0d13",
    color: "#e8eaf0",
    fontFamily: "system-ui, -apple-system, 'Segoe UI', sans-serif",
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    padding: "0 16px 48px",
  } as CSSProperties,
  inner: { width: "min(760px, 100%)" } as CSSProperties,
  header: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    padding: "28px 0 8px",
  } as CSSProperties,
  brand: { fontSize: 22, fontWeight: 300, letterSpacing: "0.18em" } as CSSProperties,
  brandBold: { fontWeight: 800, letterSpacing: "0.02em" } as CSSProperties,
  signIn: {
    background: "#1f6f4a",
    border: "1px solid #2c9a67",
    borderRadius: 8,
    color: "#fff",
    padding: "9px 20px",
    fontSize: 14,
    fontWeight: 600,
    cursor: "pointer",
  } as CSSProperties,
  h1: { fontSize: 28, fontWeight: 800, margin: "36px 0 10px", lineHeight: 1.25 } as CSSProperties,
  h2: { fontSize: 17, fontWeight: 700, margin: "30px 0 8px" } as CSSProperties,
  p: { fontSize: 15, lineHeight: 1.65, margin: "0 0 12px", opacity: 0.92 } as CSSProperties,
  li: { fontSize: 15, lineHeight: 1.65, opacity: 0.92, marginBottom: 6 } as CSSProperties,
  card: {
    background: "#10141c",
    border: "1px solid rgba(255,255,255,0.12)",
    borderRadius: 12,
    padding: "18px 20px",
    margin: "18px 0",
  } as CSSProperties,
  footer: {
    marginTop: 48,
    paddingTop: 18,
    borderTop: "1px solid rgba(255,255,255,0.1)",
    fontSize: 13,
    opacity: 0.7,
    lineHeight: 1.7,
  } as CSSProperties,
  link: { color: "#7fd4a8", textDecoration: "underline" } as CSSProperties,
};

function Shell({ children, onSignIn }: { children: ReactNode; onSignIn?: () => void }) {
  return (
    <div style={ui.page}>
      <div style={ui.inner}>
        <header style={ui.header}>
          <a href="/" style={{ color: "inherit", textDecoration: "none" }}>
            <span style={ui.brand}>
              BASEBALL <span style={ui.brandBold}>brAIn</span>
            </span>
          </a>
          {onSignIn ? (
            <button type="button" style={ui.signIn} onClick={onSignIn}>
              Sign in
            </button>
          ) : (
            <a href="/?signin=1" style={{ ...ui.signIn, textDecoration: "none" }}>
              Sign in
            </a>
          )}
        </header>
        {children}
        <footer style={ui.footer}>
          Baseball brAIn is a product of Clearmeadow Partners LLC, 16768 Matisse Drive,
          Delray Beach, FL 33446. Contact:{" "}
          <a href="mailto:aroncm@gmail.com" style={ui.link}>
            aroncm@gmail.com
          </a>
          <br />
          <a href="/?page=terms" style={ui.link}>
            Terms of Service
          </a>{" "}
          &nbsp;·&nbsp;{" "}
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
      <h1 style={ui.h1}>Advanced pitching-decision analytics for Major League Baseball clubs</h1>
      <p style={ui.p}>
        Baseball brAIn analyzes every pitch of every game and gives club staff decision
        support for one of the hardest calls in baseball: when to change the pitcher.
        The platform scores each starter's condition pitch by pitch, compares him against
        the club's available relievers, and marks the moments where a change is warranted.
      </p>
      <h2 style={ui.h2}>What club users get</h2>
      <ul>
        <li style={ui.li}>
          <strong>Game Replays.</strong> A pitch-by-pitch review of each game showing how
          the model's assessment moved and where it reached a trigger.
        </li>
        <li style={ui.li}>
          <strong>Game Briefings.</strong> A morning email summarizing each game's pitching
          decisions and the moments that mattered.
        </li>
        <li style={ui.li}>
          <strong>Live triggers.</strong> During games, the model tracks the starter in real
          time and marks Prep and Pull Now moments as they happen.
        </li>
      </ul>
      <div style={ui.card}>
        <h2 style={{ ...ui.h2, margin: "0 0 8px" }}>Text alerts (Hook Trigger Alerts)</h2>
        <p style={ui.p}>
          Club staff with a Baseball brAIn account can choose to receive a text message when
          the model reaches a pitching-change trigger in their club's live games. Enrollment
          is by opt-in only: a user enters their mobile number and agrees inside their account
          settings, or provides written consent that their administrator records. We never
          enroll a number without consent.
        </p>
        <p style={{ ...ui.p, marginBottom: 0 }}>
          Message frequency varies with the game schedule. Message and data rates may apply.
          Reply STOP to opt out at any time, or HELP for help. See our{" "}
          <a href="/?page=terms" style={ui.link}>Terms of Service</a> and{" "}
          <a href="/?page=privacy" style={ui.link}>Privacy Policy</a>.
        </p>
      </div>
      <p style={ui.p}>
        Access to the platform is by invitation to Major League Baseball club personnel.
        For inquiries, contact{" "}
        <a href="mailto:aroncm@gmail.com" style={ui.link}>
          aroncm@gmail.com
        </a>
        .
      </p>
    </Shell>
  );
}

function Terms() {
  return (
    <Shell>
      <h1 style={ui.h1}>Terms of Service</h1>
      <p style={ui.p}>Effective date: August 21, 2026</p>
      <p style={ui.p}>
        Baseball brAIn (the "Service") is operated by Clearmeadow Partners LLC
        ("we", "us"). By using the Service you agree to these terms.
      </p>
      <h2 style={ui.h2}>1. Accounts and access</h2>
      <p style={ui.p}>
        Accounts are created by invitation for authorized Major League Baseball club
        personnel and our own staff. You are responsible for keeping your credentials
        confidential and for activity under your account. We may suspend accounts that
        misuse the Service or share access outside their organization.
      </p>
      <h2 style={ui.h2}>2. The analytics</h2>
      <p style={ui.p}>
        The Service provides analytical models and decision support. It does not make
        decisions for you, and we do not guarantee any outcome from acting or not acting
        on a model output. The Service is provided as is, without warranties of any kind.
      </p>
      <h2 style={ui.h2}>3. Text alerts</h2>
      <p style={ui.p}>
        Users may opt in to receive automated text alerts when the model reaches a
        pitching-change trigger in their club's live games. Consent is collected in
        account settings or as written consent recorded by an administrator. Message
        frequency varies with the game schedule. Message and data rates may apply.
        Reply STOP to any message to opt out, or HELP for help. Opting out of texts
        does not affect your account or email briefings. Carriers are not liable for
        delayed or undelivered messages.
      </p>
      <h2 style={ui.h2}>4. Intellectual property</h2>
      <p style={ui.p}>
        The Service, its models, and its outputs are the property of Clearmeadow
        Partners LLC. Club data access is scoped to your organization under your
        organization's agreement with us.
      </p>
      <h2 style={ui.h2}>5. Contact</h2>
      <p style={ui.p}>
        Questions about these terms: <a href="mailto:aroncm@gmail.com" style={ui.link}>aroncm@gmail.com</a>,
        or Clearmeadow Partners LLC, 16768 Matisse Drive, Delray Beach, FL 33446.
      </p>
    </Shell>
  );
}

function Privacy() {
  return (
    <Shell>
      <h1 style={ui.h1}>Privacy Policy</h1>
      <p style={ui.p}>Effective date: August 21, 2026</p>
      <h2 style={ui.h2}>What we collect</h2>
      <p style={ui.p}>
        Account information (name, work email, role, club affiliation), a mobile phone
        number if you opt in to text alerts, and basic usage information needed to
        operate and secure the Service. The baseball data we analyze is game data, not
        personal data about you.
      </p>
      <h2 style={ui.h2}>How we use it</h2>
      <p style={ui.p}>
        To provide the Service: signing you in, scoping your access to your club,
        sending email briefings you are enrolled in, and sending text alerts you have
        opted in to. We do not sell personal information.
      </p>
      <h2 style={ui.h2}>Text messaging</h2>
      <p style={ui.p}>
        Phone numbers are collected only through opt-in, and each opt-in is recorded
        with a timestamp and who recorded it. No mobile information will be shared with
        third parties or affiliates for marketing or promotional purposes. Text
        messaging originator opt-in data and consent will not be shared with any third
        parties, except our messaging delivery provider solely to deliver the messages.
        Reply STOP to opt out at any time.
      </p>
      <h2 style={ui.h2}>Retention and security</h2>
      <p style={ui.p}>
        We keep account and consent records while your account is active and as needed
        to meet legal and carrier requirements. Access to personal information is
        limited to staff who need it to operate the Service.
      </p>
      <h2 style={ui.h2}>Contact</h2>
      <p style={ui.p}>
        Privacy questions: <a href="mailto:aroncm@gmail.com" style={ui.link}>aroncm@gmail.com</a>,
        or Clearmeadow Partners LLC, 16768 Matisse Drive, Delray Beach, FL 33446.
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
