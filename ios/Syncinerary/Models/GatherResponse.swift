struct GatherResponse: Decodable, Sendable {
    let deckSize: Int

    enum CodingKeys: String, CodingKey {
        case deckSize = "deck_size"
    }
}
