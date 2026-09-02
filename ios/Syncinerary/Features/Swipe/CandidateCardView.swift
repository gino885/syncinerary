import SwiftUI

struct CandidateCardView: View {
    let candidate: CandidateCard
    let photo: CandidatePhoto?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading) {
                CandidatePhotoView(
                    photo: photo,
                    placeName: candidate.nameCanonical
                )

                Text(candidate.nameCanonical)
                    .font(.title)
                    .bold()

                if let originalName = candidate.nameOriginalLang {
                    Text(originalName)
                        .font(.title3)
                        .foregroundStyle(.secondary)
                }

                if let area = candidate.area {
                    Label(area, systemImage: "mappin.and.ellipse")
                }

                SourceBadgesView(badges: candidate.sourceBadges)

                if let description = candidate.description {
                    Text(description)
                        .font(.subheadline)
                    if let source = candidate.descriptionSource {
                        Label("From \(source)", systemImage: "sparkles")
                            .font(.footnote)
                            .foregroundStyle(.blue)
                    }
                }

                if let delegateBadge = candidate.delegateBadge {
                    DelegateBadgeView(badge: delegateBadge)
                }

                Label(
                    "^[\(candidate.durationEstimateMin) minute](inflect: true)",
                    systemImage: "clock"
                )

                if let category = candidate.category {
                    Label(category.capitalized, systemImage: "tag")
                }

                if let address = candidate.address {
                    Text(address)
                        .foregroundStyle(.secondary)
                }

                SourcePostsView(posts: candidate.sourcePosts)

                if let notice = candidate.dietaryNotice {
                    Label(notice, systemImage: "exclamationmark.triangle")
                        .foregroundStyle(.orange)
                        .accessibilityLabel("Dietary information: \(notice)")
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding()
            .background(.blue.opacity(0.06))
            .clipShape(.rect(cornerRadius: AppLayout.cardCornerRadius))
            .padding()
        }
    }
}

#Preview {
    CandidateCardView(
        candidate: CandidateCard(
            id: UUID(),
            type: "attraction",
            nameCanonical: "Odori Park",
            nameOriginalLang: "大通公園",
            latitude: 43.0605,
            longitude: 141.3469,
            area: "Sapporo Chuo",
            address: "Odorinishi, Sapporo",
            category: "park",
            priceTier: 1,
            durationEstimateMin: 60,
            dietaryTags: [],
            dietaryNotice: nil,
            description: "Lanterns along the whole park at dusk.",
            descriptionSource: "TikTok",
            sourceBadges: [
                SourceBadge(
                    kind: "attached_by_you",
                    label: "Attached by you",
                    contributorName: "Gino",
                    url: "https://www.tiktok.com/@traveler/video/7481234567890123456",
                    platform: "TikTok"
                )
            ],
            sourcePosts: [
                SourcePost(
                    platform: "tiktok",
                    label: "TikTok",
                    url: "https://www.tiktok.com/@traveler/video/7481234567890123456",
                    authorName: "Travel Notes",
                    highlight: "Lanterns along the whole park at dusk."
                )
            ],
            delegateBadge: nil
        ),
        photo: nil
    )
}
