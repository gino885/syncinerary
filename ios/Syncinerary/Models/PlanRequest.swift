struct PlanRequest: Encodable, Sendable {
    let dayStart: String
    let dayEnd: String

    static let standard = PlanRequest(dayStart: "08:00:00", dayEnd: "20:00:00")
}
