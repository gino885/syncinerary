# City day controls

The trip creator assigns time to selected cities before searching for places.
Keep the existing setup form and its typography. Add a Days per city section
after Dates, with a native stepper per city and an optional Main city picker.
The total allocation is visible; Continue requires it to match the trip dates.
Explicit edits take precedence over the suggested balanced allocation.

Use the existing Canvas, Surface, Ink, Faded and Jade asset tokens in their
light/dark variants. System body for city names, caption for allocation status,
and monospaced digits for counts. No new colors or display face are needed.
The signature element is the city's editable day count beside its name.

Critique: a new hero card or percentage meter would distract from the decision.
Use plain form rows and native accessible steppers instead. Show no discovery
ratios or provider terms in setup. Keep only the allocation status needed to
enable Continue, and reuse the existing Reduce Motion-aware transition.

## Visual review

The actual component was rendered with the production view model and color
assets in an isolated iPhone 17 Pro simulator preview. Light, dark and the
largest accessibility text size are recorded next to this plan. City names
and controls remain readable without truncation; the form scrolls at the
largest size. The native picker stacks its label and value there. The first
review caught “1 days”, corrected through the English plural catalog and
verified again. No decorative container, ratio meter or new color was added.
The full app build passed; the complete trip-creation flow was not manually
operated through the simulator.
