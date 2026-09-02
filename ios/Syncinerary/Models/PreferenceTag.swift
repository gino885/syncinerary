import Foundation

struct PreferenceTag: Identifiable, Hashable, Sendable {
    let value: String
    let title: String

    var id: String { value }
}
