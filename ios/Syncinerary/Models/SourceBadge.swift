struct SourceBadge: Decodable, Hashable, Sendable {
    let kind: String
    let label: String
    let contributorName: String?

    enum CodingKeys: String, CodingKey {
        case kind
        case label
        case contributorName = "contributor_name"
    }
}
