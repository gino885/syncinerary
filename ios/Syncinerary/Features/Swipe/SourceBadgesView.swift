import SwiftUI

struct SourceBadgesView: View {
    let badges: [SourceBadge]

    var body: some View {
        if !badges.isEmpty {
            ViewThatFits(in: .horizontal) {
                HStack {
                    badgeLabels
                }

                VStack(alignment: .leading) {
                    badgeLabels
                }
            }
        }
    }

    @ViewBuilder
    private var badgeLabels: some View {
        ForEach(badges, id: \.self) { badge in
            // A badge with a public origin opens it outward: the platform's
            // own app when installed, the system browser otherwise. The post
            // is never rendered in here. A badge without one stays plain.
            if let url = badge.linkURL {
                Link(destination: url) {
                    Label(badge.label, systemImage: symbol(for: badge.kind))
                        .underline()
                }
                .font(.subheadline)
                .foregroundStyle(color(for: badge.kind))
                .accessibilityLabel(badge.accessibilityLabel)
            } else {
                Label(badge.label, systemImage: symbol(for: badge.kind))
                    .font(.subheadline)
                    .foregroundStyle(color(for: badge.kind))
                    .accessibilityLabel(badge.accessibilityLabel)
            }
        }
    }

    private func symbol(for kind: String) -> String {
        switch kind {
        case "classic": "mappin.circle.fill"
        case "trending": "flame.fill"
        case "discovered": "map.fill"
        case "attached_by_you": "heart.fill"
        default: "person.2.fill"
        }
    }

    private func color(for kind: String) -> Color {
        switch kind {
        case "trending": .orange
        case "discovered": .green
        case "attached_by_you": .pink
        default: .blue
        }
    }
}
