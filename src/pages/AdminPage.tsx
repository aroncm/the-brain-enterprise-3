import { useCallback, useEffect, useMemo, useState, type FormEvent } from "react";
import { Plus, Trash2, X } from "lucide-react";
import {
  type AdminUserRecord,
  type TeamRecipientRecord,
  addTeamRecipient,
  deleteAdminUser,
  deleteTeamRecipient,
  inviteAdminUser,
  listAdminUsers,
  listTeamRecipients,
  setAdminUserPassword,
  updateAdminUser,
  updateTeamRecipient,
} from "../api";
import { useAuth } from "../context/AuthContext";

type Team = { abbr: string; name: string };
type Tab = "users" | "recipients";

export function AdminPage({ allTeams }: { allTeams: Team[] }) {
  const [tab, setTab] = useState<Tab>("users");
  return (
    <section className="workflow theme-mobian admin-workflow">
      <article className="panel admin-panel">
        <header className="admin-tabs" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={tab === "users"}
            className={`admin-tab${tab === "users" ? " admin-tab--active" : ""}`}
            onClick={() => setTab("users")}
          >
            Users
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={tab === "recipients"}
            className={`admin-tab${tab === "recipients" ? " admin-tab--active" : ""}`}
            onClick={() => setTab("recipients")}
          >
            Recipients
          </button>
        </header>
        {tab === "users" ? <UsersTab allTeams={allTeams} /> : <RecipientsTab allTeams={allTeams} />}
      </article>
    </section>
  );
}

function UsersTab({ allTeams }: { allTeams: Team[] }) {
  const { user: currentUser } = useAuth();
  const [users, setUsers] = useState<AdminUserRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editingUserId, setEditingUserId] = useState<string | null>(null);
  const [inviteOpen, setInviteOpen] = useState(false);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const next = await listAdminUsers();
      setUsers(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load users");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const onDelete = async (target: AdminUserRecord) => {
    if (!confirm(`Remove ${target.email || target.user_id} from Baseball brAIn?`)) return;
    try {
      await deleteAdminUser(target.user_id);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    }
  };

  const onSetPassword = async (target: AdminUserRecord) => {
    const next = prompt(
      `Set a temporary password for ${target.email || target.user_id}.\n` +
        `They'll sign in at baseballbrain.club with this password and can rotate it later.\n\n` +
        `Minimum 8 characters.`,
      "",
    );
    if (!next) return;
    if (next.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    try {
      await setAdminUserPassword(target.user_id, next);
      alert(`Password set for ${target.email || target.user_id}. Share it with them out-of-band.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Set password failed");
    }
  };

  return (
    <div className="admin-section">
      <div className="admin-section__header">
        <div>
          <h2 className="admin-section__title">Users</h2>
          <p className="admin-section__hint">
            Invite Baseball brAIn admins and viewers. Admins see every team and can manage other users.
            Viewers only see the teams you assign them.
          </p>
        </div>
        <button
          type="button"
          className="admin-primary-button"
          onClick={() => setInviteOpen(true)}
        >
          <Plus size={14} />
          <span>Invite user</span>
        </button>
      </div>

      {error ? <div className="admin-error">{error}</div> : null}

      {loading ? (
        <div className="admin-loading">Loading users…</div>
      ) : users.length === 0 ? (
        <div className="admin-empty">No users yet. Invite the first one above.</div>
      ) : (
        <table className="admin-table">
          <thead>
            <tr>
              <th>Email</th>
              <th>Role</th>
              <th>Teams</th>
              <th>Created</th>
              <th aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {users.map((row) => (
              <tr key={row.user_id}>
                <td>
                  <strong>{row.email || "(no email)"}</strong>
                  {row.full_name ? <div className="admin-table__sub">{row.full_name}</div> : null}
                </td>
                <td>
                  <span className={`admin-role-pill admin-role-pill--${row.role}`}>{row.role}</span>
                </td>
                <td>
                  {row.role === "admin" ? (
                    <span className="admin-table__sub">All teams</span>
                  ) : row.team_abbrs.length === 0 ? (
                    <span className="admin-table__sub">—</span>
                  ) : (
                    <div className="admin-team-chips">
                      {row.team_abbrs.map((abbr) => (
                        <span key={abbr} className="admin-team-chip">{abbr}</span>
                      ))}
                    </div>
                  )}
                </td>
                <td className="admin-table__sub">
                  {row.created_at ? new Date(row.created_at).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" }) : "—"}
                </td>
                <td className="admin-row-actions">
                  <button
                    type="button"
                    className="admin-text-button"
                    onClick={() => setEditingUserId(row.user_id)}
                  >
                    Edit
                  </button>
                  <button
                    type="button"
                    className="admin-text-button"
                    onClick={() => { void onSetPassword(row); }}
                    title="Set a temporary password (for invite or recovery troubleshooting)"
                  >
                    Set password
                  </button>
                  {row.user_id !== currentUser?.id ? (
                    <button
                      type="button"
                      className="admin-icon-button admin-icon-button--danger"
                      aria-label={`Remove ${row.email || row.user_id}`}
                      onClick={() => { void onDelete(row); }}
                    >
                      <Trash2 size={14} />
                    </button>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {editingUserId ? (
        <EditUserModal
          user={users.find((u) => u.user_id === editingUserId) ?? null}
          allTeams={allTeams}
          isSelf={editingUserId === currentUser?.id}
          onClose={() => setEditingUserId(null)}
          onSaved={async () => {
            setEditingUserId(null);
            await refresh();
          }}
        />
      ) : null}

      {inviteOpen ? (
        <InviteUserModal
          allTeams={allTeams}
          onClose={() => setInviteOpen(false)}
          onInvited={async () => {
            setInviteOpen(false);
            await refresh();
          }}
        />
      ) : null}
    </div>
  );
}

function InviteUserModal({
  allTeams,
  onClose,
  onInvited,
}: {
  allTeams: Team[];
  onClose: () => void;
  onInvited: () => Promise<void> | void;
}) {
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<"admin" | "viewer">("viewer");
  const [selectedTeams, setSelectedTeams] = useState<Set<string>>(new Set());
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const toggleTeam = (abbr: string) => {
    setSelectedTeams((prev) => {
      const next = new Set(prev);
      if (next.has(abbr)) next.delete(abbr);
      else next.add(abbr);
      return next;
    });
  };

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await inviteAdminUser({
        email: email.trim(),
        role,
        team_abbrs: role === "admin" ? [] : Array.from(selectedTeams).sort(),
      });
      await onInvited();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Invite failed");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <ModalShell title="Invite user" onClose={onClose}>
      <form onSubmit={onSubmit} className="admin-form">
        <label className="admin-field">
          <span className="admin-field__label">Email</span>
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="admin-field__input"
            placeholder="user@example.com"
          />
        </label>
        <fieldset className="admin-field">
          <legend className="admin-field__label">Role</legend>
          <div className="admin-radio-row">
            <label className="admin-radio">
              <input type="radio" name="role" checked={role === "viewer"} onChange={() => setRole("viewer")} />
              <span>Viewer</span>
            </label>
            <label className="admin-radio">
              <input type="radio" name="role" checked={role === "admin"} onChange={() => setRole("admin")} />
              <span>Admin (all teams)</span>
            </label>
          </div>
        </fieldset>
        {role === "viewer" ? (
          <fieldset className="admin-field">
            <legend className="admin-field__label">Assigned teams</legend>
            <TeamCheckboxGrid allTeams={allTeams} selected={selectedTeams} onToggle={toggleTeam} />
          </fieldset>
        ) : null}
        {error ? <div className="admin-error">{error}</div> : null}
        <div className="admin-form__actions">
          <button type="button" className="admin-secondary-button" onClick={onClose}>Cancel</button>
          <button type="submit" className="admin-primary-button" disabled={submitting}>
            {submitting ? "Sending invite…" : "Send invite"}
          </button>
        </div>
      </form>
    </ModalShell>
  );
}

function EditUserModal({
  user,
  allTeams,
  isSelf,
  onClose,
  onSaved,
}: {
  user: AdminUserRecord | null;
  allTeams: Team[];
  isSelf: boolean;
  onClose: () => void;
  onSaved: () => Promise<void> | void;
}) {
  const [role, setRole] = useState<"admin" | "viewer">(user?.role ?? "viewer");
  const [selectedTeams, setSelectedTeams] = useState<Set<string>>(new Set(user?.team_abbrs ?? []));
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setRole(user?.role ?? "viewer");
    setSelectedTeams(new Set(user?.team_abbrs ?? []));
  }, [user?.user_id, user?.role, user?.team_abbrs]);

  if (!user) return null;

  const toggleTeam = (abbr: string) => {
    setSelectedTeams((prev) => {
      const next = new Set(prev);
      if (next.has(abbr)) next.delete(abbr);
      else next.add(abbr);
      return next;
    });
  };

  const onSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await updateAdminUser(user.user_id, {
        role,
        team_abbrs: role === "admin" ? [] : Array.from(selectedTeams).sort(),
      });
      await onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <ModalShell title={`Edit ${user.email || user.user_id}`} onClose={onClose}>
      <form onSubmit={onSubmit} className="admin-form">
        <fieldset className="admin-field">
          <legend className="admin-field__label">Role</legend>
          <div className="admin-radio-row">
            <label className="admin-radio">
              <input
                type="radio"
                name="role"
                checked={role === "viewer"}
                onChange={() => setRole("viewer")}
                disabled={isSelf}
              />
              <span>Viewer</span>
            </label>
            <label className="admin-radio">
              <input type="radio" name="role" checked={role === "admin"} onChange={() => setRole("admin")} />
              <span>Admin (all teams)</span>
            </label>
          </div>
          {isSelf ? (
            <p className="admin-field__hint">You cannot demote your own admin role.</p>
          ) : null}
        </fieldset>
        {role === "viewer" ? (
          <fieldset className="admin-field">
            <legend className="admin-field__label">Assigned teams</legend>
            <TeamCheckboxGrid allTeams={allTeams} selected={selectedTeams} onToggle={toggleTeam} />
          </fieldset>
        ) : null}
        {error ? <div className="admin-error">{error}</div> : null}
        <div className="admin-form__actions">
          <button type="button" className="admin-secondary-button" onClick={onClose}>Cancel</button>
          <button type="submit" className="admin-primary-button" disabled={submitting}>
            {submitting ? "Saving…" : "Save changes"}
          </button>
        </div>
      </form>
    </ModalShell>
  );
}

function TeamCheckboxGrid({
  allTeams,
  selected,
  onToggle,
}: {
  allTeams: Team[];
  selected: Set<string>;
  onToggle: (abbr: string) => void;
}) {
  return (
    <div className="admin-team-grid">
      {allTeams.map((team) => (
        <label key={team.abbr} className="admin-team-cell">
          <input type="checkbox" checked={selected.has(team.abbr)} onChange={() => onToggle(team.abbr)} />
          <span className="admin-team-cell__abbr">{team.abbr}</span>
          <span className="admin-team-cell__name">{team.name}</span>
        </label>
      ))}
    </div>
  );
}

function RecipientsTab({ allTeams }: { allTeams: Team[] }) {
  const [selectedTeam, setSelectedTeam] = useState<string>(allTeams[0]?.abbr ?? "ATL");
  const [recipients, setRecipients] = useState<TeamRecipientRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [newEmail, setNewEmail] = useState("");
  const [newName, setNewName] = useState("");
  const [adding, setAdding] = useState(false);

  const refresh = useCallback(async (team: string) => {
    setLoading(true);
    setError(null);
    try {
      const rows = await listTeamRecipients(team);
      setRecipients(rows);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load recipients");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh(selectedTeam);
  }, [selectedTeam, refresh]);

  const onAdd = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    setAdding(true);
    try {
      await addTeamRecipient(selectedTeam, newEmail.trim(), newName.trim() || null);
      setNewEmail("");
      setNewName("");
      await refresh(selectedTeam);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add recipient");
    } finally {
      setAdding(false);
    }
  };

  const onToggleEnabled = async (row: TeamRecipientRecord) => {
    try {
      await updateTeamRecipient(row.id, { briefings_enabled: !row.briefings_enabled });
      await refresh(selectedTeam);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Update failed");
    }
  };

  const onRemove = async (row: TeamRecipientRecord) => {
    if (!confirm(`Remove ${row.email} from ${row.team_abbr} recipients?`)) return;
    try {
      await deleteTeamRecipient(row.id);
      await refresh(selectedTeam);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    }
  };

  const teamOptions = useMemo(() => allTeams, [allTeams]);

  return (
    <div className="admin-section">
      <div className="admin-section__header">
        <div>
          <h2 className="admin-section__title">Recipients</h2>
          <p className="admin-section__hint">
            People who receive the Game Briefings email automatically when each game's postgame artifact compiles.
          </p>
        </div>
        <label className="admin-team-select">
          <span>Team</span>
          <select value={selectedTeam} onChange={(e) => setSelectedTeam(e.target.value)}>
            {teamOptions.map((team) => (
              <option key={team.abbr} value={team.abbr}>{team.abbr} — {team.name}</option>
            ))}
          </select>
        </label>
      </div>

      <form onSubmit={onAdd} className="admin-recipient-form">
        <input
          type="email"
          required
          value={newEmail}
          onChange={(e) => setNewEmail(e.target.value)}
          className="admin-field__input"
          placeholder="email@example.com"
        />
        <input
          type="text"
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          className="admin-field__input"
          placeholder="Display name (optional)"
        />
        <button type="submit" className="admin-primary-button" disabled={adding}>
          <Plus size={14} />
          <span>{adding ? "Adding…" : "Add recipient"}</span>
        </button>
      </form>

      {error ? <div className="admin-error">{error}</div> : null}

      {loading ? (
        <div className="admin-loading">Loading recipients…</div>
      ) : recipients.length === 0 ? (
        <div className="admin-empty">No recipients for {selectedTeam} yet.</div>
      ) : (
        <table className="admin-table">
          <thead>
            <tr>
              <th>Email</th>
              <th>Name</th>
              <th>Briefings enabled</th>
              <th aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {recipients.map((row) => (
              <tr key={row.id}>
                <td><strong>{row.email}</strong></td>
                <td className="admin-table__sub">{row.name ?? "—"}</td>
                <td>
                  <label className="admin-switch">
                    <input
                      type="checkbox"
                      checked={row.briefings_enabled}
                      onChange={() => { void onToggleEnabled(row); }}
                    />
                    <span>{row.briefings_enabled ? "On" : "Off"}</span>
                  </label>
                </td>
                <td className="admin-row-actions">
                  <button
                    type="button"
                    className="admin-icon-button admin-icon-button--danger"
                    aria-label={`Remove ${row.email}`}
                    onClick={() => { void onRemove(row); }}
                  >
                    <Trash2 size={14} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function ModalShell({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="admin-modal" role="dialog" aria-modal="true">
      <div className="admin-modal__backdrop" onClick={onClose} />
      <div className="admin-modal__card">
        <header className="admin-modal__header">
          <h3>{title}</h3>
          <button type="button" className="admin-icon-button" aria-label="Close" onClick={onClose}>
            <X size={16} />
          </button>
        </header>
        <div className="admin-modal__body">{children}</div>
      </div>
    </div>
  );
}
