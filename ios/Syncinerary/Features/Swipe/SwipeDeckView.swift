import SwiftUI

/// The pile of cards. The top card follows the finger, tilts, and shows a
/// stamp; past the threshold it flies off and the decision is reported, under
/// it it springs back. The buttons under the deck ask for the same flight
/// through `throwRequest`, so a tap and a swipe look identical.
struct SwipeDeckView: View {
    let cards: [CandidateCard]
    let photos: [UUID: CandidatePhoto]
    @Binding var throwRequest: SwipeDecision?
    let onDecision: (SwipeDecision) -> Void
    let onDetails: (CandidateCard) -> Void

    @State private var dragOffset = CGSize.zero
    @State private var topOpacity = 1.0
    @State private var isThrowing = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    private let decisionDistance = 120.0
    private let mustGoDistance = 150.0
    private let visibleCards = 3

    var body: some View {
        ZStack {
            ForEach(Array(cards.prefix(visibleCards).enumerated()), id: \.element.id) { index, card in
                SwipeCardView(candidate: card, photo: photos[card.id], onDetails: { onDetails(card) })
                    // The stamps ride in with the drag: further you pull,
                    // more solid the stamp, and it shrinks onto the card as
                    // if being pressed down.
                    .overlay(alignment: .topLeading) {
                        if index == 0 {
                            StampView(mark: .liked)
                                .scaleEffect(1.6 - 0.6 * likeProgress)
                                .opacity(likeProgress)
                                .padding(AppTheme.spacingXL)
                        }
                    }
                    .overlay(alignment: .topTrailing) {
                        if index == 0 {
                            StampView(mark: .passed)
                                .scaleEffect(1.6 - 0.6 * nopeProgress)
                                .opacity(nopeProgress)
                                .padding(AppTheme.spacingXL)
                        }
                    }
                    .overlay(alignment: .center) {
                        if index == 0 {
                            StampView(mark: .mustGo)
                                .scaleEffect(1.6 - 0.6 * mustGoProgress)
                                .opacity(mustGoProgress)
                        }
                    }
                    .scaleEffect(index == 0 ? 1 : 1 - Double(index) * 0.04, anchor: .bottom)
                    .offset(
                        x: index == 0 ? dragOffset.width : 0,
                        y: index == 0 ? dragOffset.height : Double(index) * 12
                    )
                    .rotationEffect(index == 0 && !reduceMotion ? rotation : .zero)
                    .opacity(index == 0 ? topOpacity : 1)
                    .zIndex(Double(visibleCards - index))
                    .allowsHitTesting(index == 0)
                    .gesture(drag, including: index == 0 ? .all : .none)
                    .accessibilityElement(children: index == 0 ? .combine : .ignore)
                    .accessibilityHidden(index != 0)
                    .accessibilityAction(named: "Like") { throwCard(.like, from: .zero) }
                    .accessibilityAction(named: "Dislike") { throwCard(.dislike, from: .zero) }
                    .accessibilityAction(named: "Must go") { throwCard(.mustHave, from: .zero) }
                    .accessibilityAction(named: "Show details") { onDetails(card) }
                    .accessibilityHint(index == 0 ? "Swipe right to like, left to dislike, up for must go." : "")
            }
        }
        // Room under the top card for the two behind it to peek out.
        .padding(.bottom, AppTheme.spacingXL)
        .animation(AppTheme.settle, value: cards.first?.id)
        .onChange(of: throwRequest) { _, request in
            guard let request else { return }
            throwRequest = nil
            throwCard(request, from: .zero)
        }
    }

    // MARK: Drag

    private var drag: some Gesture {
        DragGesture(minimumDistance: 8)
            .onChanged { value in
                guard !isThrowing else { return }
                dragOffset = value.translation
            }
            .onEnded { value in
                guard !isThrowing else { return }
                let translation = value.translation
                let predicted = value.predictedEndTranslation
                let upwards = -translation.height > abs(translation.width)
                if upwards,
                   -translation.height > mustGoDistance || -predicted.height > mustGoDistance * 2.5 {
                    throwCard(.mustHave, from: translation)
                } else if translation.width > decisionDistance
                    || predicted.width > decisionDistance * 2.5 {
                    throwCard(.like, from: translation)
                } else if translation.width < -decisionDistance
                    || predicted.width < -decisionDistance * 2.5 {
                    throwCard(.dislike, from: translation)
                } else {
                    withAnimation(AppTheme.settle) {
                        dragOffset = .zero
                    }
                }
            }
    }

    private var rotation: Angle {
        .degrees(max(-16, min(16, dragOffset.width / 12)))
    }

    private var verticalDominant: Bool {
        dragOffset.height < 0 && -dragOffset.height > abs(dragOffset.width)
    }

    private var likeProgress: Double {
        verticalDominant ? 0 : max(0, min(1, dragOffset.width / decisionDistance))
    }

    private var nopeProgress: Double {
        verticalDominant ? 0 : max(0, min(1, -dragOffset.width / decisionDistance))
    }

    private var mustGoProgress: Double {
        verticalDominant ? max(0, min(1, -dragOffset.height / mustGoDistance)) : 0
    }

    // MARK: Flight

    private func throwCard(_ decision: SwipeDecision, from translation: CGSize) {
        guard !isThrowing, !cards.isEmpty else { return }
        isThrowing = true
        if reduceMotion {
            withAnimation(AppTheme.fade) {
                topOpacity = 0
            } completion: {
                finish(decision)
            }
            return
        }
        let target: CGSize = switch decision {
        case .dislike:
            CGSize(width: -720, height: translation.height * 1.5)
        case .mustHave:
            CGSize(width: translation.width, height: -1100)
        case .like, .likeWithNote:
            CGSize(width: 720, height: translation.height * 1.5)
        }
        withAnimation(AppTheme.cardThrow) {
            dragOffset = target
        } completion: {
            finish(decision)
        }
    }

    /// The next card must appear at rest, so the reset is not animated; the
    /// cards behind it still glide forward through the deck's animation.
    private func finish(_ decision: SwipeDecision) {
        var transaction = Transaction()
        transaction.disablesAnimations = true
        withTransaction(transaction) {
            dragOffset = .zero
            topOpacity = 1
        }
        onDecision(decision)
        isThrowing = false
    }
}
