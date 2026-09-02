import SwiftUI

/// Everything known about a place, as a sheet from the deck: the photo, the
/// name, facts, provenance links, the posts behind it, address, and any
/// dietary reminder.
struct CandidateDetailView: View {
    let candidate: CandidateCard
    let photo: CandidatePhoto?

    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: AppTheme.spacingM) {
                    CandidatePhotoView(photo: photo, placeName: candidate.nameCanonical)

                    Text(candidate.nameCanonical)
                        .font(AppType.name)
                        .foregroundStyle(AppTheme.ink)

                    if let originalName = candidate.nameOriginalLang {
                        Text(originalName)
                            .font(.title3)
                            .foregroundStyle(AppTheme.faded)
                    }

                    MetaLabel(metaLine)

                    SourceBadgesView(badges: candidate.sourceBadges)

                    if let description = candidate.description {
                        Text(description)
                            .foregroundStyle(AppTheme.ink)
                        if let source = candidate.descriptionSource {
                            MetaLabel("via \(source)")
                        }
                    }

                    if let delegateBadge = candidate.delegateBadge {
                        DelegateBadgeView(badge: delegateBadge)
                    }

                    if let address = candidate.address {
                        Text(address)
                            .font(.subheadline)
                            .foregroundStyle(AppTheme.faded)
                    }

                    SourcePostsView(posts: candidate.sourcePosts)

                    if let notice = candidate.dietaryNotice {
                        HStack(alignment: .top, spacing: AppTheme.spacingS) {
                            Rectangle()
                                .fill(AppTheme.stamp)
                                .frame(width: 2)
                                .accessibilityHidden(true)
                            Text(notice)
                                .font(.subheadline)
                                .italic()
                                .foregroundStyle(AppTheme.stamp)
                        }
                        .fixedSize(horizontal: false, vertical: true)
                        .accessibilityLabel("Dietary information: \(notice)")
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding()
            }
            .journalPage()
            .navigationTitle("Details")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done", action: dismiss.callAsFunction)
                }
            }
        }
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
        parts.append(String(repeating: "$", count: max(1, candidate.priceTier)))
        return parts.joined(separator: " · ")
    }
}
