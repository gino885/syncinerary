# Trip preparation additions

Audience: friends arranging one shared trip. Preserve the existing cobalt and
lemon system. Checklist: finish booking tasks. Stay: identify the hotel already
booked. Stop notes: extract one actionable detail from a saved post.

Tokens: cobalt #3452DF, lemon #FBE587, ink #17233D, canvas #F2F5FF,
surface #FFFFFF, faded #56617B; use existing asset variants, including dark mode.
Type: rounded system display for page titles, system body for tasks and notes,
monospaced digits only for the checklist completion count.

Checklist uses a plain working list with check circles, editable text, and a
small completion count. No hero card. Its signature is trip-specific tasks
named after the actual city transfer or scheduled venue. Add/edit opens a form.
Stay puts an "Already booked?" entry before suggested stays. Search returns
verified hotel names and addresses; the traveler confirms the matching hotel.
The field remains available even if automatic suggestions are empty.
Stop advice is one short sentence with an outward source link beneath the
place name. A food recommendation is labelled only when the source recommends
food. No fabricated tip when the saved evidence is descriptive or absent.

Critique: a celebratory progress banner would compete with unfinished tasks;
removed it. No extra tinted note container inside an existing stop card.
Use the check-circle state as the only new visual accent. Avoid duplicate
highlight text alongside the note. All controls are at least 44pt, content
wraps at accessibility sizes, and no new repeating animations are introduced.

Checklist is shared. Suggestions are idempotent; manual edits, completion, and
deletions survive refresh. Generated titles are checks, not claims that a
particular service or ticket is available. Existing-booking entry records the
traveler's statement; it does not verify a reservation with the hotel.
