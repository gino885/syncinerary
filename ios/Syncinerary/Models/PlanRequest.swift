struct PlanRequest: Encodable, Hashable, Sendable {
    let dayStart: String
    let dayEnd: String

    /// Matches the backend default day window, which runs to 21:00 so a
    /// dinner seating fits inside it.
    static let standard = PlanRequest(dayStart: "08:00:00", dayEnd: "21:00:00")

    enum CodingKeys: String, CodingKey {
        case dayStart = "day_start"
        case dayEnd = "day_end"
    }
}
