# Manual additions and edits after itinerary creation

Implemented September 18, 2026. This file replaces the earlier proposal.

## User flow

Open a generated itinerary and use Edit plan, Add a place under a day, or
Edit stop from a stop's swipe action or context menu.

- Add a saved place, search for a verified place or restaurant, or resolve an
  Instagram, TikTok or RedNote post using the existing link attachment flow.
- Choose the day, start time and visit duration in half-hour increments.
- Reorder stops, remove them, or change their day and time.
- Preview changes validates the exact draft. Adjust this day can find new
  times while retaining every selected place and each requested duration.
- Review the diff and choose Use this plan or Keep current plan. Cancel leaves
  the active itinerary untouched. Search selection and post attachment can
  save a candidate even if the user subsequently cancels the itinerary edit.

This implementation edits real places and meals within the existing trip
cities and dates. It does not add a city/date editor or locationless events.
Fixed reservations cannot move or be removed. Bulk reordering is disabled on
those days; individual non-fixed stops remain editable.

## Validation and persistence

Structured requests contain the base version, traveler, candidate IDs and
exact schedule. Names and locations come from persisted candidates. No LLM
interprets manual choices, and no discovery agent reruns during an edit.

Validation checks trip membership, account ownership for account-bound members,
candidate ownership, city-day allocation, known dietary conflicts, opening
hours, overlap, transit feasibility, fatigue, walking and the original daily
schedule bounds. Legacy trips without explicit city days use the existing
route's city where available. Infeasible edits return an error on the draft;
they do not silently discard places or change the active plan.

Only changed days are routed. All requested places are required; exact edits
also fix their requested start times. Adjust this day releases start times on
that day while retaining reservations. Other days retain their nodes' content.

A successful preview writes a new proposed version and a user_request replan
event. The existing approve/reject routes control activation. Old versions and
nodes remain immutable. Active-version and pending-event checks run again
under a version lock after transit validation to catch concurrent changes.
The draft survives an API failure; a persisted pending proposal can be recovered
through the existing pending-update mechanism.

Manual versions retain schedule bounds and recompute stop and transit totals.
Old generation scores and narrative are not presented as descriptions of the
edited plan. Removed places remain in the version's unplaced wishlist.

## Relationship to Reel discovery

The 60% target remains Reel-backed candidate cards divided by all unique
candidate cards across the combined discovery deck. A manual place needs no
Reel. The editor never removes a manual choice to meet that target or invents
social evidence. Manually selected search results preserve their provider
source and record the selecting traveler.

## API and implementation

- GET /trips/{trip_id}/itinerary/edit-places: saved places, or ephemeral search
  results when q is supplied; requires traveler_id and day.
- POST /trips/{trip_id}/itinerary/edit-places: verify and persist one selected
  provider place ID, deduplicating repeat selections.
- POST /trips/{trip_id}/itinerary/edits: validate a full structured draft and
  return the existing replan proposal/diff shape.
- Existing pending, approve and reject replan routes remain the save workflow.

Core logic is in syncinerary/agents/manual_itinerary.py. API orchestration is
in syncinerary/api/routers/itinerary_edits.py. The iOS editor, picker, stop form
and draft model live in Features/Itinerary. No new database migration or
production dependency was required for this feature.

## Verification

See evidence/manual-itinerary/verification.md for test results and limits.
Screenshots cover the itinerary, editor, stop form, place picker and review
screen in light, dark and accessibility-extra-large text modes. They use
isolated fixture data, not a live provider session.
