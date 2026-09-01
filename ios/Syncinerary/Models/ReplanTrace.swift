struct ReplanTrace: Decodable, Sendable {
    let trigger: ReplanTraceTrigger
    let affectedNodes: [ReplanAffectedNode]
    let alternativesConsidered: [ReplanAlternative]
    let downstreamChanges: [ReplanDownstreamChange]

    enum CodingKeys: String, CodingKey {
        case trigger
        case affectedNodes = "affected_nodes"
        case alternativesConsidered = "alternatives_considered"
        case downstreamChanges = "downstream_changes"
    }
}
