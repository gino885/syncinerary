import Foundation

struct PreferenceSelection: Hashable, Sendable {
    private(set) var selected: Set<String> = []

    func contains(_ tag: PreferenceTag) -> Bool {
        selected.contains(tag.value)
    }

    mutating func toggle(_ tag: PreferenceTag) {
        if selected.contains(tag.value) {
            selected.remove(tag.value)
        } else {
            selected.insert(tag.value)
        }
    }

    func values(in catalog: [PreferenceTag]) -> [String] {
        catalog.compactMap { selected.contains($0.value) ? $0.value : nil }
    }

    func summary(in catalog: [PreferenceTag], empty: String) -> String {
        let titles = catalog.compactMap { selected.contains($0.value) ? $0.title : nil }
        guard !titles.isEmpty else { return empty }
        let visible = titles.prefix(2).joined(separator: ", ")
        let remaining = titles.count - 2
        return remaining > 0 ? "\(visible) +\(remaining)" : visible
    }

    static func tripSummary(
        interests: PreferenceSelection,
        dietary: PreferenceSelection
    ) -> String {
        let interestSummary = interests.summary(
            in: PreferenceCatalog.interests,
            empty: "Choose interests"
        )
        let avoids = dietary.values(in: PreferenceCatalog.dietaryExcludes)
        return avoids.isEmpty ? interestSummary : "\(interestSummary) · \(avoids.count) to avoid"
    }
}
