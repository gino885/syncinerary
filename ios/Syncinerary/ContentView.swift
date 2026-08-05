import SwiftUI

struct ContentView: View {
    @State private var status: String = "Checking backend..."

    var body: some View {
        VStack(spacing: 20) {
            Text("Syncinerary")
                .font(.largeTitle)
                .bold()
            Text("M0 Scaffold")
                .foregroundStyle(.secondary)
            Text(status)
                .padding()
                .background(.thinMaterial)
                .clipShape(RoundedRectangle(cornerRadius: 12))
        }
        .padding()
        .task {
            await checkBackend()
        }
    }

    private func checkBackend() async {
        do {
            let result = try await APIClient.shared.health()
            status = "Backend: \(result.status) (\(result.milestone))"
        } catch {
            status = "Backend unreachable: \(error.localizedDescription)"
        }
    }
}

#Preview {
    ContentView()
}
