import SwiftUI

struct ItineraryStopRow: View {
    let stop: ItineraryStop

    var body: some View {
        VStack(alignment: .leading) {
            LabeledContent(stop.name, value: stop.timeRange)
                .bold()

            if let meal = stop.mealLabel {
                Label(meal, systemImage: "fork.knife")
                    .font(.footnote.weight(.semibold))
                    .foregroundStyle(.orange)
            }

            if let area = stop.area {
                Label(area, systemImage: "mappin")
                    .foregroundStyle(.secondary)
            }

            SourceBadgesView(badges: stop.sourceBadges)

            if let description = stop.description {
                Text(description)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }

            if let source = stop.descriptionSource {
                Label("From \(source)", systemImage: "sparkles")
                    .font(.footnote)
                    .foregroundStyle(.blue)
            }

            if stop.transitFromPrevMin > 0 {
                Label(
                    "^[\(stop.transitFromPrevMin) minute](inflect: true) by \(stop.transitLabel)",
                    systemImage: "figure.walk"
                )
                .foregroundStyle(.secondary)
            }

            SourcePostsView(posts: stop.sourcePosts)
        }
        // A row with links keeps them reachable one by one; a row without
        // any reads as one element, as before.
        .accessibilityElement(children: hasLinks ? .contain : .combine)
    }

    private var hasLinks: Bool {
        !stop.sourcePosts.isEmpty || stop.sourceBadges.contains { $0.linkURL != nil }
    }
}
