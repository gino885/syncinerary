import Foundation

struct LoadingLine: Hashable, Sendable {
    let text: LocalizedStringResource
    let symbolName: String

    // LocalizedStringResource is Sendable but not Hashable, and the identity
    // that matters here is which line this is, not what it currently reads in.
    static func == (lhs: Self, rhs: Self) -> Bool {
        lhs.text.key == rhs.text.key && lhs.symbolName == rhs.symbolName
    }

    func hash(into hasher: inout Hasher) {
        hasher.combine(text.key)
        hasher.combine(symbolName)
    }
}
