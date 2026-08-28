import SwiftUI

struct CandidatePhotoView: View {
    let photo: CandidatePhoto?
    let placeName: String

    var body: some View {
        ZStack(alignment: .bottomTrailing) {
            if let photo {
                AsyncImage(url: photo.photoURL) { phase in
                    switch phase {
                    case let .success(image):
                        image
                            .resizable()
                            .scaledToFill()
                            .accessibilityHidden(true)
                    case .empty:
                        ProgressView("Loading photo")
                    case .failure:
                        placePlaceholder
                    @unknown default:
                        placePlaceholder
                    }
                }

                if photo.provider == "google_places" {
                    Text(attribution(for: photo))
                        .font(.footnote)
                        .foregroundStyle(.white)
                        .padding(6)
                        .background(.black.opacity(0.72))
                        .clipShape(.rect(cornerRadius: 8))
                        .padding(8)
                }
            } else {
                placePlaceholder
            }
        }
        .aspectRatio(4 / 3, contentMode: .fit)
        .clipped()
        .clipShape(.rect(cornerRadius: AppLayout.cardCornerRadius))
        .accessibilityLabel("Photo of \(placeName)")
    }

    private var placePlaceholder: some View {
        Rectangle()
            .fill(.blue.gradient)
            .overlay {
                Image(systemName: "photo.on.rectangle.angled")
                    .font(.largeTitle)
                    .foregroundStyle(.white)
                    .accessibilityHidden(true)
            }
    }

    private func attribution(for photo: CandidatePhoto) -> String {
        let names = photo.attributions.map(\.displayName).joined(separator: ", ")
        return names.isEmpty ? "Google Places" : "Google Places · Photo by \(names)"
    }
}
