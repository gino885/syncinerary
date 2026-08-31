import SwiftUI

struct LodgingOptionRow: View {
    let option: LodgingOption
    let isSelected: Bool

    var body: some View {
        HStack(alignment: .top) {
            VStack(alignment: .leading) {
                Text(option.name)
                    .font(.headline)
                if let area = option.area {
                    Label(area, systemImage: "mappin.and.ellipse")
                        .foregroundStyle(.secondary)
                }
                Text("Price level: \(String(repeating: "$", count: option.priceTier))")
                if let address = option.address {
                    Text(address)
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
            }
            Spacer()
            Image(systemName: isSelected ? "checkmark.circle.fill" : "circle")
                .foregroundStyle(isSelected ? .blue : .secondary)
                .accessibilityHidden(true)
        }
        .contentShape(.rect)
        .accessibilityElement(children: .combine)
        .accessibilityValue(isSelected ? "Selected" : "Not selected")
    }
}
