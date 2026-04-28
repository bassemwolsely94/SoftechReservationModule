# Prompt: Improve Reservations (Frontend + Backend) While Keeping Existing Workflow

You are a senior full-stack engineer working on this project.

## Goal
Improve the Reservations experience with a better GUI and more reliable data flow **without changing the existing business workflow**.
Also update backend data source for customers to use **`localcustomers`** instead of **`personsdata`**.

## Mandatory constraints
1. Keep all current reservation statuses, transitions, and permissions exactly as-is.
2. Keep existing API contracts whenever possible; if a change is necessary, provide backward compatibility.
3. Do not break existing pages that depend on current endpoints.
4. Keep Arabic UI labels and RTL support.
5. Add clear loading, empty, and error states in the UI.
6. Preserve filtering/search behavior and branch-based visibility rules.

## Backend tasks
1. Find all backend code paths where customer data is fetched from `personsdata`.
2. Replace those reads with `localcustomers`.
3. Keep response shape identical to current API response.
4. If field names differ between tables, map `localcustomers` fields to the expected response keys.
5. Add graceful fallback handling if a customer record is missing.
6. Add/adjust tests for:
   - customer fetch by id
   - customer search/list used by reservations
   - reservation creation/edit that requires customer lookup

## Frontend tasks (Reservations GUI)
1. Improve layout and usability of the Reservations Kanban while preserving workflow:
   - cleaner top filter bar (search, branch, priority)
   - sticky/filter toolbar where useful
   - clear card hierarchy (name, phone, branch, priority, time)
2. Add robust query states:
   - skeleton/loading state
   - empty state per column
   - error banner with retry button
3. Keep current actions and transitions unchanged (status changes, details modal, image upload).
4. Improve accessibility:
   - keyboard focus visibility
   - proper button labels/aria where needed
   - color contrast for priority/status badges

## Data/Query reliability
1. Normalize reservations query data safely to array before rendering.
2. Prevent duplicate declarations / merge-artifact regressions.
3. Add guard against accidental conflict markers in source before build.

## Deliverables
1. Code changes grouped into logical commits:
   - backend data source switch (`personsdata` -> `localcustomers`)
   - frontend reservations UI improvements
   - tests and build guards
2. Short migration note if backend schema mapping is required.
3. Test evidence:
   - backend tests
   - frontend build
   - any lint checks
4. Brief changelog in plain language for non-technical users.

## Acceptance criteria
- Reservations workflow behaves exactly the same from user perspective.
- Customer data for reservations is sourced from `localcustomers` only.
- UI is clearer and easier to use with visible loading/error/empty states.
- No build/parsing regressions.
