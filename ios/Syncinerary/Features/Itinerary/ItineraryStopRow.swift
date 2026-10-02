import SwiftUI

/// One line of the day's timetable: the times in the margin, then how you
/// got here and what you do once you arrive.
struct ItineraryStopRow: View {
    let stop: ItineraryStop
    @ScaledMetric(relativeTo: .body) private var timeColumnWidth = 56
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    var body: some View {
        let layout = dynamicTypeSize.isAccessibilitySize
            ? AnyLayout(VStackLayout(alignment: .leading, spacing: AppTheme.spacingS))
            : AnyLayout(HStackLayout(alignment: .top, spacing: AppTheme.spacingL))
        layout {
            VStack(alignment: .leading, spacing: 2) {
                Text(stop.startTime.prefix(5))
                    .font(AppType.monoBody)
                    .bold()
                    .monospacedDigit()
                    .foregroundStyle(AppTheme.accent)
                Text(stop.endTime.prefix(5))
                    .font(AppType.mono)
                    .monospacedDigit()
                    .foregroundStyle(AppTheme.faded)
            }
            .fixedSize(horizontal: true, vertical: false)
            .frame(width: dynamicTypeSize.isAccessibilitySize ? nil : timeColumnWidth, alignment: .leading)

            VStack(alignment: .leading, spacing: AppTheme.spacingS) {
                if stop.transitFromPrevMin > 0 {
                    if let url = stop.directionsURL {
                        Link(destination: url) {
                            TransitLegView(minutes: stop.transitFromPrevMin, mode: stop.transitFromPrevMode)
                                .underline()
                                .frame(minHeight: AppLayout.minimumTapHeight, alignment: .leading)
                        }
                        .accessibilityLabel("Open directions in Google Maps")
                    } else {
                        TransitLegView(minutes: stop.transitFromPrevMin, mode: stop.transitFromPrevMode)
                    }
                }

                Text(stop.name)
                    .font(AppType.rowTitle)
                    .foregroundStyle(AppTheme.ink)

                if !metaLine.isEmpty {
                    MetaLabel(verbatim: metaLine)
                }

                SourceBadgesView(badges: stop.sourceBadges)

                if let tip = stop.socialTip {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(tip.kind == "food" ? "Food tip" : "Before you go")
                            .font(.caption.weight(.semibold))
                        Text(tip.text).font(.subheadline).fixedSize(horizontal: false, vertical: true)
                        Link(destination: tip.url) {
                            Text("\(tip.source) post ↗")
                                .font(.caption)
                                .frame(minHeight: 44, alignment: .leading)
                        }
                    }
                } else if let description = stop.description {
                    Text(description)
                        .font(.subheadline)
                        .foregroundStyle(AppTheme.faded)
                        .lineLimit(3)
                }

                SourcePostsView(posts: stop.sourcePosts)
            }
        }
        .padding(AppTheme.spacingL)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(AppTheme.surface, in: .rect(cornerRadius: 20))
        // A row with links keeps them reachable one by one; a row without
        // any reads as one element.
        .accessibilityElement(children: hasLinks ? .contain : .combine)
    }

    private var hasLinks: Bool {
        stop.directionsURL != nil || !stop.sourcePosts.isEmpty || stop.sourceBadges.contains { $0.linkURL != nil }
    }

    private var metaLine: String {
        var parts: [String] = []
        if let meal = stop.mealLabel {
            parts.append(meal)
        }
        if let area = stop.area {
            parts.append(area)
        }
        return parts.joined(separator: " · ")
    }
}
