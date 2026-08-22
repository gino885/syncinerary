import SwiftUI

struct CandidateCardView: View {
    let candidate: CandidateCard

    var body: some View {
        ScrollView {
            VStack(alignment: .leading) {
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
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding()
            .background(.thinMaterial)
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
            dietaryTags: []
        )
    )
}
