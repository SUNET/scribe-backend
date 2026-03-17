# Sunet Scribe – Development Overview

This document describes the core architecture, control model, and provisioning logic of Sunet Scribe.  
It is intended for developers and system administrators working on the codebase.

Sunet Scribe is a multi-tenant system using federated authentication, typically via SWAMID / SAML.  
User accounts are created automatically at first login and managed automatically through provisioning rules, while administrators retain the ability to override automated decisions.

---

## System Hierarchy

Sunet Scribe is structured as a multi-tenant system with the following hierarchy:

System → Accounts → Realms → Users

Administrative permissions follow the same structure.

Each level represents a scope boundary for administration and provisioning.

- **System**: the entire installation
- **Account**: an organisation using the system
- **Realm**: a login domain within an account
- **Users**: authenticated users belonging to a realm

### Example System Hierarchy
```
System
├─ System administrators
└─ Accounts
   ├─ University_A
   │  ├─ Local administrators
   │  └─ Realms
   │     └─ una.se
   │        └─ Users
   │
   └─ University_B
      ├─ Local administrators
      └─ Realms
         ├─ unb.se
         │  └─ Users
         └─ stud.unb.se
            └─ Users
```

---

## Administrative Roles

Two administrative roles exist in the system.

### System Administrator

System administrators manage the entire installation.

They can:

- create and manage accounts
- configure system-wide settings
- assign local administrators
- view all realms and users

System administrators are global and not restricted by account or realm scope.

### Local Administrator

Local administrators manage users within an account.

Their administrative scope can be limited to one or more realms within that account.

Local administrators can:

- manage users within their assigned realms
- activate or deactivate users
- assign users to groups
- configure provisioning rules within the account

A local administrator may have access to:

- one realm
- multiple realms
- all realms within the account

The role itself does not change. Only the **realm scope** differs.

---

## Administrative Scope

Administrative scope determines which users an administrator can manage.

Example:

**Account:** University_B

**Local administrator scope:**

- unb.se
- stud.unb.se

In this example, the administrator can only manage users whose login domain belongs to these realms.

Administrative scope always remains limited to realms that belong to the administrator's account.

System administrators manage the entire system.

Local administrators manage users within an account. Their administrative scope can include one or more realms within that account.

---

## Authentication and Identity Attributes

Users authenticate via an external Identity Provider (IdP).

Authentication typically provides attributes via SAML, such as:

- `email`
- `preferred_username`
- `affiliation`
- `domain`

These attributes are used by the provisioning engine to determine how a user account should be handled.

---

## Provisioning Model

From v.1.3.0 and onwards user accounts can be created and updated automatically through **provisioning rules**.

Provisioning rules are evaluated every time a user logs in.

Each rule consists of:

- **Attribute name**  
  Example: `email`, `preferred_username`, `affiliation`

- **Condition**  
  Example: `Equals`, `Contains`, `Starts with`, `Regex match`

- **Match value**

- **Actions**
  - `Activate`
  - `Deactivate`
  - `Assign user to group`

If a user's attributes match the rule, the rule's actions are applied. If no rules applies or no rules are created (or prior to V1.3.0) the user account is left disabled and not part of any group. In that case an administrator needs to manually provision the user.

---

## Provisioning Rule Evaluation

Provisioning rules are evaluated during login using the following flow:
```
Login event
└─ Identity attributes received from IdP
   └─ Provisioning rules evaluated
      └─ Conflict resolution
         └─ Manual override
            └─ Final user state
```
The final user state determines:

- whether the user is active
- which group the user belongs to
- whether administrative privileges apply

---

## Conflict Resolution

When multiple provisioning rules match the same user, the following rules apply:

- **Deactivate overrides Activate**
- **The last matching rule determines group assignment**
- **A user can belong to only one group**

All enabled provisioning rules are evaluated on every login.

---

## Manual Overrides

Administrators can manually modify user state.

Examples include:

- activating or deactivating a user
- assigning a user to a different group
- granting administrative privileges

Manual actions always override provisioning rules.

If an administrator manually activates, deactivates, or assigns a group to a user, that state will persist and will not be reset on subsequent logins.

Manual changes remain in effect until an administrator changes them again.

---

## Design Principles and Invariants

When working on the provisioning logic, keep the following model in mind:

Identity attributes → Provisioning rules → Conflict resolution → Manual override → Final user state

System invariants:

- The system hierarchy (System → Account → Realm → User) defines all scope boundaries for provisioning and administration.
- Provisioning rules are limited by the administrator's realm permissions and can be configured to apply to a subset of those realms.
- Provisioning runs on every login.
- All enabled rules are evaluated.
- Deactivate overrides Activate.
- Group assignment is determined by the last matching rule.
- Manual administrative changes persist across logins.
- Administrator privileges are always assigned manually and must not be managed by provisioning rules.
