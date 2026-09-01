enum ReplanStatus: String, Decodable, Sendable {
    case pending
    case approved
    case rejected
}
