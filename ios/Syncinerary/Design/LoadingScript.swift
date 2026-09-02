import Foundation

/// What the board says while the agent works. Each wait has its own script
/// so the words match what the server is doing.
struct LoadingScript: Hashable, Sendable {
    let title: String
    let lines: [LoadingLine]

    static func gathering(city: String) -> LoadingScript {
        LoadingScript(
            title: "Finding places in \(city)",
            lines: [
                LoadingLine(text: "Searching Instagram, TikTok, and RedNote", symbolName: "flame.fill"),
                LoadingLine(text: "Reading public captions", symbolName: "text.bubble.fill"),
                LoadingLine(text: "Counting where posts agree", symbolName: "checkmark.seal.fill"),
                LoadingLine(text: "Checking each place on the map", symbolName: "map.fill"),
                LoadingLine(text: "Removing weak matches", symbolName: "eye.slash.fill"),
                LoadingLine(text: "Putting trending finds first", symbolName: "shuffle"),
            ]
        )
    }

    static let deck = LoadingScript(
        title: "Dealing your cards",
        lines: [
            LoadingLine(text: "Laying out the deck", symbolName: "rectangle.stack.fill"),
            LoadingLine(text: "Adding your friends' finds", symbolName: "person.2.fill"),
        ]
    )

    static let shortlist = LoadingScript(
        title: "Counting the votes",
        lines: [
            LoadingLine(text: "Tallying the votes", symbolName: "checklist"),
            LoadingLine(text: "Finding what everyone agreed on", symbolName: "person.2.fill"),
            LoadingLine(text: "Leaving disliked places out", symbolName: "hand.thumbsdown.fill"),
        ]
    )

    static let stay = LoadingScript(
        title: "Comparing places to stay",
        lines: [
            LoadingLine(text: "Comparing places to stay", symbolName: "bed.double.fill"),
            LoadingLine(text: "Finding a base near the action", symbolName: "mappin.and.ellipse"),
        ]
    )

    static func plan(city: String) -> LoadingScript {
        LoadingScript(
            title: "Building your \(city) days",
            lines: [
                LoadingLine(text: "Checking the forecast", symbolName: "cloud.rain.fill"),
                LoadingLine(text: "Fitting the day together", symbolName: "calendar.badge.clock"),
                LoadingLine(text: "Keeping your must-gos safe", symbolName: "star.fill"),
                LoadingLine(text: "Making time for meals", symbolName: "fork.knife"),
                LoadingLine(text: "Measuring every walk", symbolName: "figure.walk"),
                LoadingLine(text: "Writing your trip story", symbolName: "text.document.fill"),
            ]
        )
    }

    static let itinerary = LoadingScript(
        title: "Unrolling the map",
        lines: [
            LoadingLine(text: "Unrolling the map", symbolName: "map.fill"),
            LoadingLine(text: "Polishing your days", symbolName: "sparkles"),
        ]
    )
}
