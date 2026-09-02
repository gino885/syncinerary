import SwiftUI

/// Where a place came from, in the margin-note voice: small caps and an
/// arrow when it opens outward (the platform's app when installed, Safari
/// otherwise). The post is never rendered in here; a badge with no public
/// URL stays plain (CLAUDE.md 8.5).
struct SourceBadgesView: View {
    let badges: [SourceBadge]

    var body: some View {
        if !badges.isEmpty {
            ViewThatFits(in: .horizontal) {
                HStack(spacing: AppTheme.spacingL) {
                    labels
                }
                VStack(alignment: .leading, spacing: AppTheme.spacingXS) {
                    labels
                }
            }
        }
    }

    @ViewBuilder
    private var labels: some View {
        ForEach(badges, id: \.self) { badge in
            if let url = badge.linkURL {
                Link(destination: url) {
                    HStack(spacing: AppTheme.spacingXS) {
                        Text(shortLabel(for: badge))
                            .underline()
                        Image(systemName: "arrow.up.right")
                            .accessibilityHidden(true)
                    }
                    .font(AppType.mono)
                    .textCase(.uppercase)
                    .foregroundStyle(tint(for: badge.kind))
                }
                .accessibilityLabel(badge.accessibilityLabel)
            } else {
                MetaLabel(shortLabel(for: badge), color: tint(for: badge.kind))
                    .accessibilityLabel(badge.accessibilityLabel)
            }
        }
    }

    /// The margin has no room for sentences: "Google Maps", "TikTok",
    /// "From Ana".
    private func shortLabel(for badge: SourceBadge) -> String {
        switch badge.kind {
        case "discovered": "Google Maps"
        case "trending": badge.platform ?? "Trending"
        case "classic": "Classic"
        case "attached_by_you": "You added this"
        default: badge.contributorName.map { "From \($0)" } ?? badge.label
        }
    }

    /// Vermilion for what other people are talking about, violet for what
    /// the group added by hand, faded ink for the place listing. Provenance
    /// is this product's point, so the human sources get the loud inks.
    private func tint(for kind: String) -> Color {
        switch kind {
        case "trending": AppTheme.stamp
        case "attached_by_you", "attached_by_group": AppTheme.violet
        default: AppTheme.faded
        }
    }
}

#Preview {
    SourceBadgesView(badges: [
        SourceBadge(kind: "trending", label: "Trending on TikTok", contributorName: nil, url: "https://www.tiktok.com/@a/video/7481234567890123456", platform: "TikTok"),
        SourceBadge(kind: "discovered", label: "Found on Google Maps", contributorName: nil, url: nil, platform: nil),
    ])
    .padding()
    .background(AppTheme.paper)
}
