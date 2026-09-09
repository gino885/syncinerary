import Foundation

struct PreferenceTag: Identifiable, Hashable, Sendable {
    /// The stable key the server reads. Never localized: the backend matches
    /// interests and dietary exclusions on these exact strings.
    let value: String
    /// English, and also the String Catalog key for the localized title.
    let title: String

    var id: String { value }

    /// Looked up at render time. A title that arrives as data is invisible to
    /// the compiler's string extraction, so these entries are added to the
    /// catalog by hand rather than found in a build.
    var localizedTitle: String {
        String(localized: String.LocalizationValue(title))
    }
}
