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
                        Text(badge.localizedLabel)
                            .underline()
                        Image(systemName: "arrow.up.right")
                            .accessibilityHidden(true)
                    }
                    .font(AppType.mono)
                    .textCase(.uppercase)
                    .foregroundStyle(tint(for: badge.kind))
                }
                .accessibilityLabel(badge.accessibilityLabel)
            } else if badge.isRecommendation {
                HStack(spacing: AppTheme.spacingXS) {
                    // SF Symbol rather than a sparkle emoji: the glyph has to
                    // render everywhere the deck does, and emoji do not.
                    Image(systemName: "sparkles")
                        .accessibilityHidden(true)
                    Text(badge.localizedLabel)
                }
                .font(AppType.mono)
                .textCase(.uppercase)
                .foregroundStyle(tint(for: badge.kind))
                .accessibilityLabel(badge.accessibilityLabel)
            } else {
                MetaLabel(verbatim: badge.localizedLabel, color: tint(for: badge.kind))
                    .accessibilityLabel(badge.accessibilityLabel)
            }
        }
    }

    /// Vermilion for what other people are talking about, violet for what
    /// the group added by hand, faded ink for the place listing. Provenance
    /// is this product's point, so the human sources get the loud inks.
    private func tint(for kind: String) -> Color {
        switch kind {
        case "trending": AppTheme.stamp
        case "attached_by_you", "attached_by_group": AppTheme.violet
        // Jade, so the recommendation reason reads as its own kind of claim
        // rather than as another source.
        case "for_you": AppTheme.jade
        default: AppTheme.faded
        }
    }
}

#Preview {
    SourceBadgesView(badges: [
        SourceBadge(kind: "trending", label: "Trending on TikTok", category: "provenance", contributorName: nil, url: "https://www.tiktok.com/@a/video/7481234567890123456", platform: "TikTok", discoveryIntents: nil),
        SourceBadge(kind: "for_you", label: "For You", category: "recommendation", contributorName: nil, url: nil, platform: nil, discoveryIntents: ["hidden_gems"]),
        SourceBadge(kind: "discovered", label: "Found on Google Maps", category: "provenance", contributorName: nil, url: nil, platform: nil, discoveryIntents: nil),
    ])
    .padding()
    .background(AppTheme.paper)
}
