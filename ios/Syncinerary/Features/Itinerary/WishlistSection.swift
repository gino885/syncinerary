import SwiftUI

struct WishlistSection: View {
    let items: [WishlistItem]

    var body: some View {
        if !items.isEmpty {
            Section("Wishlist, not placed") {
                ForEach(items) { item in
                    VStack(alignment: .leading) {
                        Text(item.name)
                            .bold()
                        Text(item.reasonText)
                            .foregroundStyle(.secondary)
                    }
                    .accessibilityElement(children: .combine)
                }
            }
        }
    }
}
