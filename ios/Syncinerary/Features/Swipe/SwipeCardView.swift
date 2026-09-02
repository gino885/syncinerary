import SwiftUI

/// A photo taped into a journal: the picture, a paper stub with the name in
/// the display serif, one line of facts, where it came from, and what the
/// post said. Everything else is one tap away in `CandidateDetailView`, so
/// the drag owns the card.
struct SwipeCardView: View {
    let candidate: CandidateCard
    let photo: CandidatePhoto?
    let onDetails: () -> Void

    var body: some View {
        VStack(spacing: 0) {
            SwipeCardHeroView(candidate: candidate, photo: photo)

            VStack(alignment: .leading, spacing: AppTheme.spacingS) {
                HStack(alignment: .firstTextBaseline, spacing: AppTheme.spacingS) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(candidate.nameCanonical)
                            .font(AppType.name)
                            .foregroundStyle(AppTheme.ink)
                            .lineLimit(2)
                        if let original = candidate.nameOriginalLang {
                            Text(original)
                                .font(.subheadline)
                                .foregroundStyle(AppTheme.faded)
                                .lineLimit(1)
                        }
                    }
                    Spacer(minLength: 0)
                    Button("Details", systemImage: "info.circle", action: onDetails)
                        .labelStyle(.iconOnly)
                        .font(.title3)
                        .foregroundStyle(AppTheme.faded)
                        .frame(minWidth: AppLayout.minimumTapHeight, minHeight: AppLayout.minimumTapHeight)
                }

                MetaLabel(metaLine, color: AppTheme.ink)

                SourceBadgesView(badges: candidate.sourceBadges)

                SourcePlatformLinksView(posts: candidate.sourcePosts)

                if let description = candidate.description {
                    Text(description)
                        .font(.subheadline)
                        .foregroundStyle(AppTheme.ink)
                        .lineLimit(2)
                }

                if let badge = candidate.delegateBadge {
                    DelegateNoteLine(badge: badge)
                }
            }
            .padding(AppTheme.spacingL)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(AppTheme.paper)
        }
        .background(AppTheme.paper)
        .clipShape(.rect(cornerRadius: AppTheme.cornerRadius))
        .overlay {
            RoundedRectangle(cornerRadius: AppTheme.cornerRadius)
                .stroke(AppTheme.rule, lineWidth: AppTheme.hairlineWidth)
        }
        .shadow(color: .black.opacity(0.16), radius: 16, y: 8)
    }

    private var metaLine: String {
        var parts: [String] = []
        if let area = candidate.area {
            parts.append(area)
        }
        if let category = candidate.category {
            parts.append(category.replacing("_", with: " "))
        }
        parts.append("\(candidate.durationEstimateMin) min")
        return parts.joined(separator: " · ")
    }
}

#Preview {
    SwipeCardView(
        candidate: CandidateCard(
            id: UUID(),
            type: "food",
            nameCanonical: "Ramen Shingen",
            nameOriginalLang: "麺屋 彩未",
            latitude: 43.05,
            longitude: 141.35,
            area: "Sapporo Chuo",
            address: "Minami 6 Jo, Sapporo",
            category: "ramen_restaurant",
            priceTier: 2,
            durationEstimateMin: 75,
            dietaryTags: [],
            dietaryNotice: nil,
            description: "Miso broth worth the queue.",
            descriptionSource: "TikTok",
            sourceBadges: [
                SourceBadge(kind: "trending", label: "Trending on TikTok", contributorName: nil, url: "https://www.tiktok.com/@traveler/video/7481234567890123456", platform: "TikTok")
            ],
            sourcePosts: [],
            delegateBadge: DelegateBadge(type: "confirm", text: "Matches your love of ramen", reasoning: "You listed ramen.")
        ),
        photo: nil,
        onDetails: { }
    )
    .padding()
    .background(AppTheme.paper)
}
