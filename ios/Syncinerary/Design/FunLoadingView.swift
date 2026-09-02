import SwiftUI

/// A page being written: the line the agent is on now, set large in the
/// display serif, with the lines it already finished fading above it. The
/// owning screen keeps its alert, so a failure is never hidden behind a
/// friendly sentence.
struct FunLoadingView: View {
    let script: LoadingScript

    @State private var lineIndex = 0
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    /// At most two finished lines stay on the page; more turns into noise.
    private var previousLines: [String] {
        guard lineIndex > 0 else { return [] }
        return Array(script.lines[max(0, lineIndex - 2)..<lineIndex])
    }

    var body: some View {
        VStack(alignment: .leading, spacing: AppTheme.spacingL) {
            EyebrowText(script.title)

            VStack(alignment: .leading, spacing: AppTheme.spacingM) {
                ForEach(previousLines, id: \.self) { line in
                    Text(line)
                        .font(AppType.subtitle)
                        .foregroundStyle(AppTheme.faded)
                        .strikethrough(color: AppTheme.rule)
                }

                Text(script.lines[lineIndex])
                    .font(AppType.name)
                    .foregroundStyle(AppTheme.ink)
                    .id(lineIndex)
                    .transition(
                        reduceMotion
                            ? .opacity
                            : .opacity.combined(with: .move(edge: .bottom))
                    )
            }

            ProgressView()
                .tint(AppTheme.stamp)
                .padding(.top, AppTheme.spacingS)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .padding(AppTheme.spacingXL)
        .padding(.top, 40)
        .background(AppTheme.paper)
        .clipped()
        .task(id: script) {
            await cycleLines()
        }
        .accessibilityElement(children: .combine)
    }

    private func cycleLines() async {
        lineIndex = 0
        while !Task.isCancelled {
            try? await Task.sleep(for: .seconds(2.4))
            guard !Task.isCancelled else { return }
            withAnimation(AppTheme.fade) {
                lineIndex = (lineIndex + 1) % script.lines.count
            }
        }
    }
}

#Preview {
    FunLoadingView(script: .gathering(city: "Sapporo"))
}
