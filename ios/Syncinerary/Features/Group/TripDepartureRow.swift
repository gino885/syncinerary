import SwiftUI

struct TripDepartureRow: View {
    let trip: TripListRow

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(alignment: .top, spacing: 16) {
                Text(trip.destination)
                    .font(.system(.title2, design: .rounded, weight: .semibold))
                    .multilineTextAlignment(.leading)
                Spacer(minLength: 0)
                Image(systemName: "arrow.up.right")
                    .font(.body.weight(.semibold))
                    .foregroundStyle(AppTheme.accent)
                    .accessibilityHidden(true)
            }
            HStack(alignment: .firstTextBaseline) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(TripDate.parse(trip.startDate)?.formatted(TripDate.short) ?? trip.startDate)
                        .font(.subheadline.monospacedDigit())
                    Text("\(trip.days) days · \(trip.memberCount) travellers")
                        .font(.caption)
                        .foregroundStyle(AppTheme.faded)
                }
                Spacer(minLength: 0)
                if trip.status == "active" {
                    Label("Active", systemImage: "checkmark.circle.fill")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(AppTheme.jade)
                }
            }
        }
        .padding(20)
        .foregroundStyle(AppTheme.ink)
        .background(AppTheme.surface, in: RoundedRectangle(cornerRadius: 22))
        .accessibilityElement(children: .combine)
    }
}
