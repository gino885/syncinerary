import Foundation

/// What the board says while the agent works. Each wait has its own script
/// so the words match what the server is doing.
struct LoadingScript: Hashable, Sendable {
    let title: String
    let lines: [String]

    static func gathering(city: String) -> LoadingScript {
        LoadingScript(
            title: "Finding places in \(city)",
            lines: [
                "Asking TikTok what's hot in \(city) 🔥",
                "Reading the captions so you don't have to 📱",
                "Counting how many posts agree ✅",
                "Checking the places exist on the map 🗺️",
                "Skipping the tourist traps 🪤",
                "Shuffling the good stuff to the top 🔀",
            ]
        )
    }

    static let deck = LoadingScript(
        title: "Dealing your cards",
        lines: [
            "Laying out the deck 🃏",
            "Adding your friends' hints 💬",
        ]
    )

    static let shortlist = LoadingScript(
        title: "Counting the votes",
        lines: [
            "Tallying the votes 🗳️",
            "Finding what everyone agreed on 🤝",
            "Politely ignoring the dislikes 🙈",
        ]
    )

    static let stay = LoadingScript(
        title: "Comparing places to stay",
        lines: [
            "Comparing pillows 🛏️",
            "Finding a bed near the action 📍",
        ]
    )

    static func plan(city: String) -> LoadingScript {
        LoadingScript(
            title: "Building your \(city) days",
            lines: [
                "Checking the forecast ☔",
                "Asking the solver nicely 🧮",
                "Keeping your must-gos safe ⭐",
                "Timing lunch for when you're hungry 🍜",
                "Measuring walks in coffee breaks ☕",
                "Writing your trip story ✍️",
            ]
        )
    }

    static let itinerary = LoadingScript(
        title: "Unrolling the map",
        lines: [
            "Unrolling the map 🗺️",
            "Polishing your days ✨",
        ]
    )
}
