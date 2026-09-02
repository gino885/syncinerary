import SwiftUI

struct CandidatePhotoView: View {
    let photo: CandidatePhoto?
    let placeName: String
    /// The deck's card fills whatever space it is given; the detail sheet
    /// keeps a 4:3 frame so the page scrolls predictably.
    var fillsContainer = false

    var body: some View {
        ZStack(alignment: .topTrailing) {
            if let photo {
                AsyncImage(url: photo.photoURL) { phase in
                    switch phase {
                    case let .success(image):
                        // The overlay keeps the image out of layout, so a wide
                        // photo cannot stretch the card past the screen.
                        Color.clear
                            .overlay {
                                image
                                    .resizable()
                                    .scaledToFill()
                            }
                            .clipped()
                            .accessibilityHidden(true)
                    case .empty:
                        placePlaceholder
                            .overlay {
                                ProgressView()
                                    .tint(AppTheme.stamp)
                            }
                    case .failure:
                        placePlaceholder
                    @unknown default:
                        placePlaceholder
                    }
                }

                if photo.provider == "google_places" {
                    Text(attribution(for: photo))
                        .font(AppType.mono)
                        .textCase(.uppercase)
                        .foregroundStyle(.white)
                        .padding(.horizontal, AppTheme.spacingS)
                        .padding(.vertical, AppTheme.spacingXS)
                        .background(.black.opacity(0.55), ignoresSafeAreaEdges: [])
                        .padding(AppTheme.spacingS)
                        .dynamicTypeSize(...DynamicTypeSize.large)
                }
            } else {
                placePlaceholder
            }
        }
        .modifier(PhotoFrameModifier(fillsContainer: fillsContainer))
        .accessibilityLabel("Photo of \(placeName)")
    }

    private var placePlaceholder: some View {
        Rectangle()
            .fill(AppTheme.ink)
            .overlay {
                Image(systemName: "photo")
                    .font(.largeTitle)
                    .foregroundStyle(AppTheme.paper)
                    .accessibilityHidden(true)
            }
    }

    private func attribution(for photo: CandidatePhoto) -> String {
        let names = photo.attributions.map(\.displayName).joined(separator: ", ")
        return names.isEmpty ? "Google Places" : "Google Places · \(names)"
    }
}
