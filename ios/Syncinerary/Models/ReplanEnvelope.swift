struct ReplanEnvelope: Decodable, Sendable {
    let type: String
    let proposal: ReplanProposalResponse
}
