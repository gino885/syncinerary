import SwiftUI

struct DelegateBadgeView: View {
    let badge: DelegateBadge

    private var icon: String {
        badge.type == "warning" ? "exclamationmark.triangle.fill" : "sparkles"
    }

    private var color: Color {
        badge.type == "warning" ? .orange : .blue
    }

    var body: some View {
        DisclosureGroup {
            Text(badge.reasoning)
                .font(.subheadline)
                .foregroundStyle(.secondary)
                .padding(.top, 4)
        } label: {
            Label(badge.text, systemImage: icon)
                .font(.subheadline)
                .bold()
                .foregroundStyle(color)
        }
        .padding()
        .background(color.opacity(0.1))
        .clipShape(.rect(cornerRadius: AppLayout.cardCornerRadius))
    }
}
