import Foundation

/// The backend sends calendar dates as `YYYY-MM-DD`. Parsing them lands on
/// UTC midnight, so formatting must also happen in GMT or a phone west of
/// Greenwich shows the day before.
enum TripDate {
    static let parseStrategy = Date.ISO8601FormatStyle().year().month().day()

    static func parse(_ value: String) -> Date? {
        try? Date(value, strategy: parseStrategy)
    }

    /// "Sep 28"
    static let short = Date.FormatStyle(timeZone: .gmt).month(.abbreviated).day()

    /// "Monday, Sep 28"
    static let weekday = Date.FormatStyle(timeZone: .gmt).weekday(.wide).month(.abbreviated).day()

    /// "Sep 28 to Oct 2", falling back to the raw strings.
    static func range(_ start: String, _ end: String) -> String {
        guard let startDate = parse(start), let endDate = parse(end) else {
            return "\(start) to \(end)"
        }
        return "\(startDate.formatted(short)) to \(endDate.formatted(short))"
    }
}
