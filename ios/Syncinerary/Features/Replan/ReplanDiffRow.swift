import SwiftUI

struct ReplanDiffRow: View {
    let systemImage: String
    let title: String
    let detail: String
    let tint: Color

    var body: some View {
        Label {
            VStack(alignment: .leading) {
                Text(title)
                    .bold()
                Text(detail)
                    .foregroundStyle(.secondary)
            }
        } icon: {
            Image(systemName: systemImage)
                .foregroundStyle(tint)
                .accessibilityHidden(true)
        }
        .accessibilityElement(children: .combine)
    }
}
