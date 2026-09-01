struct ReplanDiff: Decodable, Sendable {
    let added: [ReplanDiffStop]
    let removed: [ReplanDiffStop]
    let moved: [ReplanMove]
    let timeChanged: [ReplanTimeChange]

    enum CodingKeys: String, CodingKey {
        case added
        case removed
        case moved
        case timeChanged = "time_changed"
    }
}
