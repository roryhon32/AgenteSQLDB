/**
 * gsap-feedback.js — Módulo de Feedback Visual de Alta Performance com GSAP Core.
 * 
 * Funcionalidades:
 *  1. disintegrate(element, options)  → Efeito "Thanos Snap" / Desintegração em partículas.
 *  2. acceptFeedback(element, options) → Efeito "Confirmação Satisfatória" com Check SVG animado,
 *                                        bounce elástico e burst de confetes em tons de verde.
 *  3. useDisintegrate / useAcceptFeedback → Hooks React compatíveis.
 * 
 * Requisitos técnicos atendidos:
 *  - 100% GSAP Core + gsap.utils (sem plugins pagos).
 *  - Orquestração precisa via gsap.timeline().
 *  - Suporte completo a limpeza com .kill() para prevenir vazamentos de memória.
 *  - Acessibilidade: Detecção de 'prefers-reduced-motion' com fallback sutil de 150ms.
 *  - Web Audio API integrado para feedback sonoro opcional sem arquivos externos.
 */

(function (global, factory) {
  if (typeof exports === 'object' && typeof module !== 'undefined') {
    module.exports = factory();
  } else if (typeof define === 'function' && define.amd) {
    define(factory);
  } else {
    global.GSAPFeedback = factory();
  }
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  // -------------------------------------------------------------------------
  // 0. Auxiliares & Detecção de Acessibilidade
  // -------------------------------------------------------------------------

  function getGSAP() {
    const g = typeof window !== 'undefined' ? (window.gsap || (typeof gsap !== 'undefined' ? gsap : null)) : null;
    if (!g) {
      console.warn('[GSAPFeedback] GSAP não foi encontrado no escopo global. Certifique-se de carregar gsap.min.js.');
    }
    return g;
  }

  function prefersReducedMotion() {
    if (typeof window === 'undefined' || !window.matchMedia) return false;
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  }

  /**
   * Sintetizador de áudio Web Audio API (sem dependência de assets .mp3 externos)
   */
  function playSuccessTone() {
    try {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (!AudioCtx) return;
      const ctx = new AudioCtx();
      const now = ctx.currentTime;

      // Nota 1: 523.25 Hz (C5)
      const osc1 = ctx.createOscillator();
      const gain1 = ctx.createGain();
      osc1.type = 'sine';
      osc1.frequency.setValueAtTime(523.25, now);
      gain1.gain.setValueAtTime(0.08, now);
      gain1.gain.exponentialRampToValueAtTime(0.001, now + 0.18);
      osc1.connect(gain1);
      gain1.connect(ctx.destination);
      osc1.start(now);
      osc1.stop(now + 0.18);

      // Nota 2: 659.25 Hz (E5) ligeiramente atrasada (+0.07s)
      const osc2 = ctx.createOscillator();
      const gain2 = ctx.createGain();
      osc2.type = 'sine';
      osc2.frequency.setValueAtTime(659.25, now + 0.07);
      gain2.gain.setValueAtTime(0.12, now + 0.07);
      gain2.gain.exponentialRampToValueAtTime(0.001, now + 0.28);
      osc2.connect(gain2);
      gain2.connect(ctx.destination);
      osc2.start(now + 0.07);
      osc2.stop(now + 0.28);
    } catch (_) {
      // Ignora silenciosamente se o navegador bloquear autoplay de áudio
    }
  }

  // -------------------------------------------------------------------------
  // 1. ANIMAÇÃO DE DELETE — "DESINTEGRAÇÃO" (Thanos Snap Style)
  // -------------------------------------------------------------------------

  /**
   * Desintegra um elemento em partículas suspensas com contração inicial,
   * dispersão orgânica e remoção segura do DOM.
   * 
   * @param {HTMLElement} element - Elemento a ser desintegrado
   * @param {Object} [options]
   * @param {Function} [options.onComplete] - Callback executado após a remoção
   * @param {Object} [options.clickPoint] - Coordenadas {x, y} para origem do stagger
   * @param {number} [options.particleSize=6] - Tamanho aproximado das partículas (4 a 8px)
   * @param {number} [options.density=55] - Quantidade total de partículas
   * @param {boolean} [options.removeOnComplete=true] - Se deve remover o elemento do DOM
   * @param {boolean} [options.collapseHeight=true] - Se deve fechar a altura suavemente na lista
   * @returns {gsap.core.Timeline|null} Timeline do GSAP para controle ou cleanup
   */
  function disintegrate(element, options = {}) {
    const gsapInstance = getGSAP();
    if (!element || !gsapInstance) {
      if (options.onComplete) options.onComplete();
      return null;
    }

    const {
      onComplete = null,
      clickPoint = null,
      particleSize = 6,
      density = 60,
      removeOnComplete = true,
      collapseHeight = true
    } = options;

    // Fallback de acessibilidade (prefers-reduced-motion)
    if (prefersReducedMotion()) {
      const fallbackTl = gsapInstance.timeline({
        onComplete: () => {
          if (removeOnComplete && element.parentNode) element.remove();
          if (onComplete) onComplete();
        }
      });
      fallbackTl.to(element, { opacity: 0, duration: 0.15, ease: 'power1.out' });
      return fallbackTl;
    }

    const rect = element.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) {
      if (removeOnComplete && element.parentNode) element.remove();
      if (onComplete) onComplete();
      return null;
    }

    // Estilo computado para herdar as cores da peça
    const compStyle = window.getComputedStyle(element);
    const bg = compStyle.backgroundColor !== 'rgba(0, 0, 0, 0)' && compStyle.backgroundColor !== 'transparent'
      ? compStyle.backgroundColor
      : '#3B82F6';
    const borderCol = compStyle.borderColor || '#1D4ED8';
    const textCol = compStyle.color || '#F1F5F9';

    const palette = [bg, borderCol, textCol, '#94A3B8', '#64748B'];

    // Container fixo de partículas isolado de overflows
    const container = document.createElement('div');
    container.className = 'gsap-particles-container';
    container.style.cssText = `
      position: fixed;
      left: 0;
      top: 0;
      width: 100vw;
      height: 100vh;
      pointer-events: none;
      z-index: 999999;
      overflow: visible;
    `;
    document.body.appendChild(container);

    // Gera a malha de partículas baseada na geometria do elemento
    const particles = [];
    const pCount = Math.min(100, Math.max(25, density));

    for (let i = 0; i < pCount; i++) {
      const p = document.createElement('div');
      p.className = 'gsap-dust-particle';

      // Dispersão sobre a superfície do elemento
      const relX = Math.random() * rect.width;
      const relY = Math.random() * rect.height;
      const posX = rect.left + relX;
      const posY = rect.top + relY;

      const size = gsapInstance.utils.random(particleSize - 2, particleSize + 2);
      const color = palette[Math.floor(Math.random() * palette.length)];

      p.style.cssText = `
        position: absolute;
        left: ${posX}px;
        top: ${posY}px;
        width: ${size}px;
        height: ${size}px;
        background: ${color};
        border-radius: ${Math.random() > 0.4 ? '1px' : '50%'};
        opacity: 0.95;
        box-shadow: 0 0 4px ${color};
        transform: translateZ(0);
      `;
      container.appendChild(p);
      particles.push({ el: p, relX, relY });
    }

    // Configuração do ponto de origem do Stagger
    let staggerOrigin = 'random';
    if (clickPoint && clickPoint.x !== undefined && clickPoint.y !== undefined) {
      particles.sort((a, b) => {
        const distA = Math.hypot(rect.left + a.relX - clickPoint.x, rect.top + a.relY - clickPoint.y);
        const distB = Math.hypot(rect.left + b.relX - clickPoint.x, rect.top + b.relY - clickPoint.y);
        return distA - distB;
      });
      staggerOrigin = 'start';
    }

    const particleEls = particles.map(p => p.el);

    // Orquestração com gsap.timeline()
    const tl = gsapInstance.timeline({
      onComplete: () => {
        container.remove();
        if (collapseHeight && element.parentNode) {
          gsapInstance.to(element, {
            height: 0,
            paddingTop: 0,
            paddingBottom: 0,
            marginTop: 0,
            marginBottom: 0,
            borderWidth: 0,
            duration: 0.22,
            ease: 'power2.inOut',
            onComplete: () => {
              if (removeOnComplete && element.parentNode) element.remove();
              if (onComplete) onComplete();
            }
          });
        } else {
          if (removeOnComplete && element.parentNode) element.remove();
          if (onComplete) onComplete();
        }
      }
    });

    // 1. Contração suave do elemento original (sucção/puxão pré-dissolução)
    tl.to(element, {
      scale: 0.98,
      opacity: 0.65,
      duration: 0.08,
      ease: 'power1.in'
    })
    // 2. Oculta o elemento original imediatamente quando as partículas iniciam
    .set(element, {
      opacity: 0
    })
    // 3. Dispersão estocástica em lote das partículas tipo "pó de dissolução"
    .to(particleEls, {
      y: () => gsapInstance.utils.random(-35, -15), // sobem levemente
      x: () => gsapInstance.utils.random(-45, 45),  // dispersão lateral
      opacity: 0,
      scale: 0.1,
      rotation: () => gsapInstance.utils.random(-50, 50),
      duration: () => gsapInstance.utils.random(0.65, 0.9),
      ease: 'power2.in',
      stagger: {
        each: 0.012,
        from: staggerOrigin
      }
    }, '-=0.04');

    return tl;
  }

  // -------------------------------------------------------------------------
  // 2. ANIMAÇÃO DE ACCEPT — "CONFIRMAÇÃO SATISFATÓRIA"
  // -------------------------------------------------------------------------

  /**
   * Dispara sequência comemorativa:
   *  - SVG de Check com animação precisa de strokeDashoffset
   *  - Bounce elástico simultâneo no card/linha (scale 1 -> 1.05 -> 1)
   *  - Flash de fundo esmeralda sutil
   *  - Burst de confetes 100% verdes com gravidade simulada
   *  - Tom suave opcional com Web Audio
   * 
   * @param {HTMLElement} element - Elemento que recebe a aprovação
   * @param {Object} [options]
   * @param {Function} [options.onComplete] - Callback após término da animação
   * @param {boolean} [options.sound=true] - Tocar feedback auditivo curto
   * @param {boolean} [options.permanentTint=false] - Se deve manter leve tom verde no fundo
   * @param {number} [options.confettiCount=10] - Quantidade de partículas de confete
   * @returns {gsap.core.Timeline|null} Timeline do GSAP
   */
  function acceptFeedback(element, options = {}) {
    const gsapInstance = getGSAP();
    if (!element || !gsapInstance) {
      if (options.onComplete) options.onComplete();
      return null;
    }

    const {
      onComplete = null,
      sound = true,
      permanentTint = false,
      confettiCount = 10
    } = options;

    // Fallback de acessibilidade (prefers-reduced-motion)
    if (prefersReducedMotion()) {
      const fallbackTl = gsapInstance.timeline({
        onComplete: () => {
          if (onComplete) onComplete();
        }
      });
      fallbackTl.to(element, {
        backgroundColor: 'rgba(16, 185, 129, 0.18)',
        duration: 0.15,
        yoyo: !permanentTint,
        repeat: permanentTint ? 0 : 1,
        ease: 'power1.inOut'
      });
      return fallbackTl;
    }

    const rect = element.getBoundingClientRect();
    const centerX = rect.left + rect.width / 2;
    const centerY = rect.top + rect.height / 2;

    // Container flutuante para checkmark e confetes
    const overlay = document.createElement('div');
    overlay.className = 'gsap-accept-overlay';
    overlay.style.cssText = `
      position: fixed;
      left: 0;
      top: 0;
      width: 100vw;
      height: 100vh;
      pointer-events: none;
      z-index: 999999;
      display: flex;
      align-items: center;
      justify-content: center;
    `;
    document.body.appendChild(overlay);

    // SVG do Checkmark circular estilizado
    const checkBadge = document.createElement('div');
    checkBadge.className = 'gsap-check-badge';
    checkBadge.style.cssText = `
      position: absolute;
      left: ${centerX - 24}px;
      top: ${centerY - 24}px;
      width: 48px;
      height: 48px;
      border-radius: 50%;
      background: rgba(16, 185, 129, 0.95);
      box-shadow: 0 4px 18px rgba(16, 185, 129, 0.45);
      display: flex;
      align-items: center;
      justify-content: center;
      transform: scale(0);
    `;

    checkBadge.innerHTML = `
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" style="overflow: visible;">
        <path class="gsap-check-path" d="M5 13l4 4L19 7" stroke="#FFFFFF" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" />
      </svg>
    `;
    overlay.appendChild(checkBadge);

    const checkPath = checkBadge.querySelector('.gsap-check-path');
    const pathLength = checkPath.getTotalLength ? checkPath.getTotalLength() : 24;

    // Prepara stroke para o efeito de desenho do traço
    gsapInstance.set(checkPath, {
      strokeDasharray: pathLength,
      strokeDashoffset: pathLength
    });

    // Criação dos confetes exclusivamente em tons de verde
    const greenShades = ['#047857', '#059669', '#10B981', '#34D399', '#6EE7B7', '#A7F3D0'];
    const confettiEls = [];
    const count = Math.max(6, Math.min(16, confettiCount));

    for (let i = 0; i < count; i++) {
      const c = document.createElement('div');
      c.className = 'gsap-green-confetti';
      const cWidth = gsapInstance.utils.random(5, 8);
      const cHeight = gsapInstance.utils.random(6, 12);
      const color = greenShades[i % greenShades.length];

      c.style.cssText = `
        position: absolute;
        left: ${centerX}px;
        top: ${centerY}px;
        width: ${cWidth}px;
        height: ${cHeight}px;
        background: ${color};
        border-radius: ${Math.random() > 0.5 ? '2px' : '50%'};
        opacity: 0;
        transform: translateZ(0);
      `;
      overlay.appendChild(c);
      confettiEls.push(c);
    }

    // Timeline principal sincronizada
    const tl = gsapInstance.timeline({
      onStart: () => {
        if (sound) playSuccessTone();
      },
      onComplete: () => {
        overlay.remove();
        if (onComplete) onComplete();
      }
    });

    // 1. Flash de background do elemento para verde esmeralda
    tl.to(element, {
      backgroundColor: 'rgba(16, 185, 129, 0.16)',
      borderColor: 'rgba(16, 185, 129, 0.45)',
      duration: 0.22,
      ease: 'power1.inOut'
    })
    // 2. Bounce suave do elemento: scale 1 -> 1.05 -> 1 com back.out(2)
    .to(element, {
      scale: 1.05,
      duration: 0.18,
      ease: 'back.out(2)'
    }, '<')
    .to(element, {
      scale: 1.0,
      duration: 0.22,
      ease: 'power2.out'
    })

    // 3. Surgimento do Badge do Checkmark
    .to(checkBadge, {
      scale: 1,
      duration: 0.25,
      ease: 'back.out(2.5)'
    }, '<')

    // 4. Animação "desenhando o check": strokeDashoffset de comprimento total -> 0
    .to(checkPath, {
      strokeDashoffset: 0,
      duration: 0.35,
      ease: 'power2.out'
    }, '-=0.15')

    // 5. Burst de confetes verdes saindo do centro do checkmark
    .add('confettiBurst', '-=0.08')
    .set(confettiEls, {
      opacity: 1
    }, 'confettiBurst')
    .to(confettiEls, {
      x: () => gsapInstance.utils.random(-65, 65),
      y: () => gsapInstance.utils.random(-80, -25),
      rotation: () => gsapInstance.utils.random(-180, 180),
      duration: 0.38,
      ease: 'power1.out',
      stagger: 0.012
    }, 'confettiBurst')
    // Simulação da gravidade puxando os confetes para baixo com fade-out
    .to(confettiEls, {
      y: '+=95',
      opacity: 0,
      rotation: '+=120',
      duration: 0.45,
      ease: 'power1.in',
      stagger: 0.012
    }, 'confettiBurst+=0.28')

    // 6. Fade-out elegante do badge do checkmark
    .to(checkBadge, {
      scale: 0.8,
      opacity: 0,
      duration: 0.22,
      ease: 'power2.in'
    }, 'confettiBurst+=0.35');

    // Restaura ou mantém a cor de fundo dependendo da opção
    if (!permanentTint) {
      tl.to(element, {
        backgroundColor: '',
        borderColor: '',
        duration: 0.35,
        ease: 'power1.out'
      }, '-=0.2');
    }

    return tl;
  }

  // -------------------------------------------------------------------------
  // 3. MICRO-INTERAÇÃO DE REJEIÇÃO — "NEGAR USUÁRIO PENDENTE"
  // -------------------------------------------------------------------------

  /**
   * Sintetizador de áudio Web Audio API para tom tátil de rejeição/recusa
   */
  function playDenyTone() {
    try {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (!AudioCtx) return;
      const ctx = new AudioCtx();
      const now = ctx.currentTime;

      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'sine';
      osc.frequency.setValueAtTime(360, now);
      osc.frequency.exponentialRampToValueAtTime(170, now + 0.14);
      gain.gain.setValueAtTime(0.08, now);
      gain.gain.exponentialRampToValueAtTime(0.001, now + 0.14);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(now);
      osc.stop(now + 0.14);
    } catch (_) {
      // Ignora autoplay bloqueado
    }
  }

  /**
   * Micro-interação de alta fidelidade para "Negar/Recusar Usuário":
   * 100% acionada por clique (onClick), sem dependência de scroll.
   *
   * Orquestração (duração ~750ms - 900ms):
   *  1. Trava imediata do botão (disabled & pointer-events: none)
   *  2. Squash tátil elástico no botão com transição de cor para crimson/vermelho (#DC2626)
   *  3. Rotação elástica do ícone SVG 'X' e micro-shake tátil de rejeição (tremor horizontal)
   *  4. Onda de choque circular (shockwave ring) translúcida expandindo-se a partir do botão
   *  5. Deslize cinético da linha com fade out (x: -35px, opacity: 0, filter blur)
   *  6. Colapso vertical suave da linha/card (height: 0, padding: 0, margin: 0) reorganizando a lista
   *
   * @param {HTMLElement} button - Botão clicado (.btn-reject-user)
   * @param {HTMLElement} rowElement - Linha (<tr> ou card) do usuário a ser rejeitado
   * @param {Object} [options]
   * @param {Function} [options.onComplete] - Callback executado ao final
   * @param {boolean} [options.sound=true] - Se deve tocar som de rejeição
   * @param {boolean} [options.removeOnComplete=true] - Se deve remover a linha do DOM
   * @returns {gsap.core.Timeline|null} Timeline GSAP criada
   */
  function rejectFeedback(button, rowElement, options = {}) {
    const gsapInstance = getGSAP();
    if (!button || !rowElement || !gsapInstance) {
      if (options.onComplete) options.onComplete();
      return null;
    }

    const {
      onComplete = null,
      sound = true,
      removeOnComplete = true
    } = options;

    // 1. Desabilita instantaneamente para evitar duplo clique
    button.disabled = true;
    button.style.pointerEvents = 'none';

    // Fallback de acessibilidade (prefers-reduced-motion)
    if (prefersReducedMotion()) {
      const fallbackTl = gsapInstance.timeline({
        onComplete: () => {
          if (removeOnComplete && rowElement.parentNode) rowElement.remove();
          if (onComplete) onComplete();
        }
      });
      fallbackTl.to(button, { backgroundColor: '#DC2626', color: '#FFFFFF', duration: 0.1 });
      fallbackTl.to(rowElement, { opacity: 0, duration: 0.15, ease: 'power1.out' });
      return fallbackTl;
    }

    if (sound) playDenyTone();

    const rect = button.getBoundingClientRect();
    const centerX = rect.left + rect.width / 2;
    const centerY = rect.top + rect.height / 2;

    // Shockwave ring container
    const shockwave = document.createElement('div');
    shockwave.className = 'gsap-reject-shockwave';
    shockwave.style.cssText = `
      position: fixed;
      left: ${centerX}px;
      top: ${centerY}px;
      width: 32px;
      height: 32px;
      margin-left: -16px;
      margin-top: -16px;
      border-radius: 50%;
      border: 2px solid #EF4444;
      background: radial-gradient(circle, rgba(239, 68, 68, 0.35) 0%, rgba(220, 38, 38, 0.05) 70%, transparent 100%);
      box-shadow: 0 0 16px rgba(239, 68, 68, 0.7);
      pointer-events: none;
      z-index: 999999;
      transform: scale(0.2);
      opacity: 0.95;
    `;
    document.body.appendChild(shockwave);

    const btnSvg = button.querySelector('svg');
    const btnSpan = button.querySelector('span');

    const tl = gsapInstance.timeline({
      onComplete: () => {
        shockwave.remove();
        if (removeOnComplete && rowElement.parentNode) {
          rowElement.remove();
        }
        if (onComplete) onComplete();
      }
    });

    // 1. Squash inicial do botão + Mudança de cor para Vermelho Carmim Alerta
    tl.to(button, {
      scale: 0.92,
      backgroundColor: '#DC2626',
      color: '#FFFFFF',
      boxShadow: '0 0 18px rgba(220, 38, 38, 0.7)',
      duration: 0.12,
      ease: 'power2.in'
    }, 0);

    // 2. Rotação elástica do ícone SVG 'X'
    if (btnSvg) {
      tl.to(btnSvg, {
        rotation: 90,
        scale: 1.25,
        duration: 0.28,
        ease: 'back.out(2.5)'
      }, 0.05);
    }

    // 3. Atualização sutil do texto para "Negado"
    if (btnSpan) {
      tl.to(btnSpan, {
        opacity: 0,
        duration: 0.08,
        onComplete: () => {
          btnSpan.textContent = 'Negado';
        }
      }, 0.04)
      .to(btnSpan, {
        opacity: 1,
        duration: 0.12
      }, 0.14);
    }

    // 4. Tremor tátil de recusa (horizontal rejection shake)
    tl.to(button, {
      x: -6,
      duration: 0.05,
      ease: 'power1.inOut'
    }, 0.12)
    .to(button, {
      x: 6,
      duration: 0.05,
      ease: 'power1.inOut'
    })
    .to(button, {
      x: -4,
      duration: 0.05,
      ease: 'power1.inOut'
    })
    .to(button, {
      x: 4,
      duration: 0.05,
      ease: 'power1.inOut'
    })
    .to(button, {
      x: 0,
      scale: 1,
      duration: 0.06,
      ease: 'power2.out'
    });

    // 5. Expansão da Shockwave ring com fade-out
    tl.to(shockwave, {
      scale: 2.8,
      opacity: 0,
      duration: 0.45,
      ease: 'power2.out'
    }, 0.15);

    // 6. Linha inteira ganha flash de borda vermelha e desliza suavemente para a esquerda
    tl.to(rowElement, {
      backgroundColor: 'rgba(239, 68, 68, 0.08)',
      borderColor: 'rgba(239, 68, 68, 0.4)',
      duration: 0.15,
      ease: 'power1.in'
    }, 0.2)
    .to(rowElement, {
      x: -35,
      opacity: 0,
      filter: 'blur(3px)',
      duration: 0.28,
      ease: 'power2.in'
    }, 0.38);

    // 7. Colapso vertical suave da linha/card reorganizando a lista de pendentes sem cortes bruscos
    tl.to(rowElement, {
      height: 0,
      minHeight: 0,
      paddingTop: 0,
      paddingBottom: 0,
      marginTop: 0,
      marginBottom: 0,
      borderTopWidth: 0,
      borderBottomWidth: 0,
      duration: 0.26,
      ease: 'power2.inOut'
    }, 0.64);

    return tl;
  }

  // -------------------------------------------------------------------------
  // 4. Suporte para React (Hooks useDisintegrate, useAcceptFeedback e useRejectFeedback)
  // -------------------------------------------------------------------------

  function createReactHooks(ReactInstance) {
    if (!ReactInstance || !ReactInstance.useRef || !ReactInstance.useEffect) {
      return {};
    }

    const { useRef, useEffect, useCallback } = ReactInstance;

    function useDisintegrate() {
      const activeTimelineRef = useRef(null);

      useEffect(() => {
        return () => {
          if (activeTimelineRef.current) {
            activeTimelineRef.current.kill();
          }
        };
      }, []);

      const trigger = useCallback((element, options = {}) => {
        if (activeTimelineRef.current) activeTimelineRef.current.kill();
        activeTimelineRef.current = disintegrate(element, options);
        return activeTimelineRef.current;
      }, []);

      return { disintegrate: trigger };
    }

    function useAcceptFeedback() {
      const activeTimelineRef = useRef(null);

      useEffect(() => {
        return () => {
          if (activeTimelineRef.current) {
            activeTimelineRef.current.kill();
          }
        };
      }, []);

      const trigger = useCallback((element, options = {}) => {
        if (activeTimelineRef.current) activeTimelineRef.current.kill();
        activeTimelineRef.current = acceptFeedback(element, options);
        return activeTimelineRef.current;
      }, []);

      return { acceptFeedback: trigger };
    }

    function useRejectFeedback() {
      const activeTimelineRef = useRef(null);

      useEffect(() => {
        return () => {
          if (activeTimelineRef.current) {
            activeTimelineRef.current.kill();
          }
        };
      }, []);

      const trigger = useCallback((button, rowElement, options = {}) => {
        if (activeTimelineRef.current) activeTimelineRef.current.kill();
        activeTimelineRef.current = rejectFeedback(button, rowElement, options);
        return activeTimelineRef.current;
      }, []);

      return { rejectFeedback: trigger };
    }

    return { useDisintegrate, useAcceptFeedback, useRejectFeedback };
  }

  // Se React estiver disponível no escopo global
  const reactHooks = typeof window !== 'undefined' && window.React
    ? createReactHooks(window.React)
    : {};

  return {
    disintegrate,
    acceptFeedback,
    rejectFeedback,
    playDenyTone,
    prefersReducedMotion,
    playSuccessTone,
    createReactHooks,
    ...reactHooks
  };
});
