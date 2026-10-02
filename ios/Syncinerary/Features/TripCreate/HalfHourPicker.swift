import SwiftUI

/// A clock picker whose selectable values match the server's scheduling grid.
struct HalfHourPicker: View {
    let title: LocalizedStringKey
    @Binding var selection: Date

    private var slots: [Date] {
        let calendar = Calendar.current
        let start = calendar.startOfDay(for: selection)
        return stride(from: 0, to: 1440, by: 30).compactMap {
            calendar.date(byAdding: .minute, value: $0, to: start)
        }
    }

    var body: some View {
        Picker(title, selection: $selection) {
            ForEach(slots, id: \.self) { date in
                Text(date, format: .dateTime.hour().minute()).tag(date)
            }
        }
    }
}
