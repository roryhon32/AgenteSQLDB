/**
 * home-interactions.js — Motor de Animações de Entrada e Microinterações da Tela Inicial do Milia AI.
 * 
 * Implementa com GSAP Core:
 *  1. Animação de Entrada Sequencial da Página (Linha amarela, Título, Descrição, 3 Cards, Banner LGPD)
 *  2. Microinterações Táteis dos 3 Cards (Hover com elevação e seta deslizante, click feedback)
 *  3. Sidebar Dinâmica: Indicador Ativo Deslizante (Sliding Pill) + Pulse sutil de Badges
 *  4. Campo de Input & Botão de Envio (Focus glow, hover com leve rotação, pulse no envio)
 *  5. Card "Seus dados estão protegidos" (Entrada com delay + Efeito Breathing sutil no Escudo)
 *  6. Pausa automática de loops em background (document.visibilitychange) para economia de CPU
 *  7. Acessibilidade total: Detecção de 'prefers-reduced-motion' com fallback suave de 150ms
 *  8. Suporte a React com hook useHomeInteractions() e cleanup via .kill()
 */

(function (global, factory) {
  if (typeof exports === 'object' && typeof module !== 'undefined') {
    module.exports = factory();
  } else if (typeof define === 'function' && define.amd) {
    define(factory);
  } else {
    global.HomeInteractions = factory();
  }
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  // -------------------------------------------------------------------------
  // 0. Auxiliares & Verificação de Ambiente
  // -------------------------------------------------------------------------

  function getGSAP() {
    return typeof window !== 'undefined' ? (window.gsap || (typeof gsap !== 'undefined' ? gsap : null)) : null;
  }

  function prefersReducedMotion() {
    if (typeof window === 'undefined' || !window.matchMedia) return false;
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  }

  // Lista de timelines ativas de looping para gerenciamento de visibilidade
  const activeLoopTimelines = new Set();
  let visibilityListenerRegistered = false;

  function registerVisibilityHandler() {
    if (visibilityListenerRegistered || typeof document === 'undefined') return;
    document.addEventListener('visibilitychange', () => {
      const isHidden = document.hidden;
      activeLoopTimelines.forEach(tl => {
        if (tl && typeof tl.pause === 'function') {
          if (isHidden) {
            tl.pause();
          } else {
            tl.resume();
          }
        }
      });
    });
    visibilityListenerRegistered = true;
  }

  // -------------------------------------------------------------------------
  // 1. ANIMAÇÃO DE ENTRADA DA PÁGINA (page load) — ~900ms a 1.1s
  // -------------------------------------------------------------------------

  /**
   * Executa a timeline orquestrada de entrada da tela inicial do chat/home.
   * 
   * @param {Object} [options]
   * @param {HTMLElement|string} [options.container="#chatWelcomeState"] - Container principal
   * @param {Function} [options.onComplete] - Callback ao finalizar
   * @param {boolean} [options.simulateReducedMotion=false] - Para testes
   * @returns {gsap.core.Timeline|null} Timeline criada
   */
  function animateHomeEntrance(options = {}) {
    const gsapInstance = getGSAP();
    if (!gsapInstance) return null;

    const {
      container = "#chatWelcomeState",
      onComplete = null,
      simulateReducedMotion = false
    } = options;

    const rootEl = typeof container === 'string' ? document.querySelector(container) : container;
    if (!rootEl) {
      if (onComplete) onComplete();
      return null;
    }

    // Seleção dos elementos da timeline
    const yellowIndicator = rootEl.querySelector(".welcome-yellow-indicator");
    const heading = rootEl.querySelector(".welcome-heading");
    const description = rootEl.querySelector(".welcome-description");
    const cards = rootEl.querySelectorAll(".welcome-cards-grid .welcome-card");
    const lgpdBanner = rootEl.querySelector(".welcome-lgpd-banner");

    // Fallback de Acessibilidade (150ms simples)
    if (prefersReducedMotion() || simulateReducedMotion) {
      const fallbackTl = gsapInstance.timeline({
        onComplete: () => {
          if (onComplete) onComplete();
        }
      });

      // Garante reset dos elementos para o estado normal sem transform
      gsapInstance.set([rootEl, yellowIndicator, heading, description, cards, lgpdBanner], {
        clearProps: "transform,opacity"
      });

      fallbackTl.fromTo(rootEl, 
        { opacity: 0 }, 
        { opacity: 1, duration: 0.15, ease: "power1.out" }
      );
      return fallbackTl;
    }

    // Timeline Única de Entrada Sequencial
    const tl = gsapInstance.timeline({
      defaults: { ease: "power2.out" },
      onComplete: () => {
        if (onComplete) onComplete();
      }
    });

    // 1. Linha amarela decorativa: scaleX 0 -> 1, transform-origin: left, duration: 0.4s
    if (yellowIndicator) {
      gsapInstance.set(yellowIndicator, { scaleX: 0, transformOrigin: "left center" });
      tl.to(yellowIndicator, {
        scaleX: 1,
        duration: 0.4,
        ease: "power2.out"
      });
    }

    // 2. Título ("Olá, Controladoria." + "Como posso ajudar hoje?"): fade + y: 16 -> 0, duration: 0.4s
    if (heading) {
      tl.fromTo(heading, 
        { opacity: 0, y: 16 }, 
        { opacity: 1, y: 0, duration: 0.4, ease: "power2.out" }, 
        "-=0.15"
      );
    }

    // 3. Texto descritivo ("Converse com seus dados..."): fade + y: 10 -> 0, duration: 0.35s
    if (description) {
      tl.fromTo(description, 
        { opacity: 0, y: 10 }, 
        { opacity: 1, y: 0, duration: 0.35, ease: "power2.out" }, 
        "-=0.2"
      );
    }

    // 4. Os 3 cards: stagger fade + y: 20 -> 0 + scale: 0.97 -> 1, duration: 0.4s, back.out(1.4)
    if (cards && cards.length > 0) {
      tl.fromTo(cards, 
        { opacity: 0, y: 20, scale: 0.97 }, 
        { 
          opacity: 1, 
          y: 0, 
          scale: 1, 
          duration: 0.4, 
          ease: "back.out(1.4)", 
          stagger: { each: 0.1, from: "start" } 
        }, 
        "-=0.15"
      );
    }

    // 5. Banner de LGPD: fade + y: 10 -> 0, duration: 0.3s
    if (lgpdBanner) {
      tl.fromTo(lgpdBanner, 
        { opacity: 0, y: 10 }, 
        { opacity: 1, y: 0, duration: 0.3, ease: "power2.out" }, 
        "-=0.1"
      );
    }

    return tl;
  }

  // -------------------------------------------------------------------------
  // 2. MICROINTERAÇÕES NOS CARDS (Consultar Margem / Analisar Custos / Buscar Informações)
  // -------------------------------------------------------------------------

  /**
   * Conecta microinterações nos cards de ação rápida:
   *  - Hover: scale 1 -> 1.02, elevação em box-shadow, seta translateX 0 -> 4px
   *  - Leave: retorno suave com mesma duration/ease
   *  - Click: scale down tátil (1 -> 0.98 -> 1 em 0.15s)
   * 
   * @param {string|NodeList|Array} [selector=".welcome-cards-grid .welcome-card"]
   */
  function initCardMicrointeractions(selector = ".welcome-cards-grid .welcome-card") {
    const gsapInstance = getGSAP();
    if (!gsapInstance || typeof document === 'undefined') return;

    const cards = typeof selector === 'string' ? document.querySelectorAll(selector) : selector;
    if (!cards) return;

    cards.forEach(card => {
      // Previne duplicação de listeners
      if (card.dataset.gsapCardInit) return;
      card.dataset.gsapCardInit = "true";

      const arrow = card.querySelector(".card-bottom-arrow svg") || card.querySelector(".card-bottom-arrow");

      // Hover In
      card.addEventListener("mouseenter", () => {
        if (prefersReducedMotion()) return;
        gsapInstance.to(card, {
          scale: 1.02,
          boxShadow: "0 14px 28px -4px rgba(8, 33, 66, 0.12), 0 4px 10px -2px rgba(8, 33, 66, 0.05)",
          borderColor: "#CBD5E1",
          duration: 0.2,
          ease: "power2.out",
          overwrite: "auto"
        });

        if (arrow) {
          gsapInstance.to(arrow, {
            x: 4,
            duration: 0.2,
            ease: "power2.out",
            overwrite: "auto"
          });
        }
      });

      // Hover Out
      card.addEventListener("mouseleave", () => {
        if (prefersReducedMotion()) return;
        gsapInstance.to(card, {
          scale: 1.0,
          boxShadow: "0 1px 3px rgba(0, 0, 0, 0.05)",
          borderColor: "#E2E8F0",
          duration: 0.2,
          ease: "power2.out",
          overwrite: "auto"
        });

        if (arrow) {
          gsapInstance.to(arrow, {
            x: 0,
            duration: 0.2,
            ease: "power2.out",
            overwrite: "auto"
          });
        }
      });

      // Click / Feedback Tátil: scale 1 -> 0.98 -> 1 (0.15s total)
      card.addEventListener("pointerdown", () => {
        if (prefersReducedMotion()) return;
        gsapInstance.timeline()
          .to(card, { scale: 0.98, duration: 0.075, ease: "power1.in" })
          .to(card, { scale: 1.0, duration: 0.075, ease: "power1.out" });
      });
    });
  }

  // -------------------------------------------------------------------------
  // 3. SIDEBAR — INDICADOR ATIVO DESLIZANTE & PULSE DE BADGES
  // -------------------------------------------------------------------------

  let activeIndicatorEl = null;

  /**
   * Garante que o indicador deslizante (sliding pill) existe no DOM da sidebar.
   */
  function ensureActiveIndicator(menuEl) {
    if (!menuEl) return null;
    let indicator = menuEl.querySelector(".sidebar-active-indicator");
    if (!indicator) {
      indicator = document.createElement("div");
      indicator.className = "sidebar-active-indicator";
      indicator.style.cssText = `
        position: absolute;
        left: 0;
        top: 0;
        width: 100%;
        background-color: var(--navy-sidebar-active, #0D2D58);
        border-radius: 8px;
        pointer-events: none;
        z-index: 1;
        opacity: 0;
        transform: translateY(0);
        transition: none;
      `;
      // Insere como primeiro filho para ficar atrás do texto e ícones
      menuEl.style.position = "relative";
      menuEl.prepend(indicator);
    }
    return indicator;
  }

  /**
   * Desliza o indicador de fundo da sidebar suavemente até o item ativo.
   * 
   * @param {HTMLElement|string} targetItem - O elemento `<li>` do menu a ser ativado
   * @param {Object} [options]
   */
  function animateNavActiveIndicator(targetItem, options = {}) {
    const gsapInstance = getGSAP();
    if (!gsapInstance || typeof document === 'undefined') return;

    const itemEl = typeof targetItem === 'string' ? document.querySelector(targetItem) : targetItem;
    if (!itemEl) return;

    const menuEl = itemEl.closest(".sidebar-menu");
    if (!menuEl) return;

    const indicator = ensureActiveIndicator(menuEl);
    if (!indicator) return;

    // Cálculo das coordenadas relativas
    const itemRect = itemEl.getBoundingClientRect();
    const menuRect = menuEl.getBoundingClientRect();
    const targetY = itemRect.top - menuRect.top;
    const targetHeight = itemRect.height;

    // Fallback de acessibilidade
    if (prefersReducedMotion()) {
      gsapInstance.set(indicator, {
        y: targetY,
        height: targetHeight,
        opacity: 1
      });
      return;
    }

    // Se o indicador ainda estava oculto (primeira renderização), faz fade-in direto na posição
    if (parseFloat(window.getComputedStyle(indicator).opacity) < 0.1) {
      gsapInstance.set(indicator, {
        y: targetY,
        height: targetHeight
      });
      gsapInstance.to(indicator, {
        opacity: 1,
        duration: 0.25,
        ease: "power2.out"
      });
    } else {
      // Desliza suavemente até o novo item ativo
      gsapInstance.to(indicator, {
        y: targetY,
        height: targetHeight,
        opacity: 1,
        duration: 0.32,
        ease: "power2.out"
      });
    }

    // Animação sutil de cor no texto e ícone do item ativo (duration: 0.25s)
    const activeLink = itemEl.querySelector("a");
    if (activeLink) {
      gsapInstance.to(activeLink, {
        color: "#FFFFFF",
        duration: 0.25,
        ease: "power2.out"
      });
    }

    // Outros itens voltam à cor secundária
    menuEl.querySelectorAll(".menu-item:not(.active) a").forEach(link => {
      gsapInstance.to(link, {
        color: "rgba(255, 255, 255, 0.72)",
        duration: 0.25,
        ease: "power2.out"
      });
    });
  }

  /**
   * Ativa o loop sutil de pulso do badge de notificações/segurança (scale 1 -> 1.08 -> 1 a cada 3-4s).
   * 
   * @param {string|HTMLElement} [badgeSelector="#sidebarSecurityBadge"]
   */
  function initBadgePulse(badgeSelector = "#sidebarSecurityBadge") {
    const gsapInstance = getGSAP();
    if (!gsapInstance || typeof document === 'undefined') return null;

    const badge = typeof badgeSelector === 'string' ? document.querySelector(badgeSelector) : badgeSelector;
    if (!badge) return null;

    if (prefersReducedMotion()) return null;

    registerVisibilityHandler();

    // Pulse lento e sutil: repete a cada 3.2s
    const badgeTl = gsapInstance.timeline({
      repeat: -1,
      yoyo: true,
      repeatDelay: 3.2
    });

    badgeTl.to(badge, {
      scale: 1.08,
      duration: 0.4,
      ease: "power1.inOut"
    });

    activeLoopTimelines.add(badgeTl);
    return badgeTl;
  }

  // -------------------------------------------------------------------------
  // 4. CAMPO DE INPUT & BOTÃO DE ENVIO
  // -------------------------------------------------------------------------

  /**
   * Conecta as microinterações de foco no input e hover/click com pulse no botão de envio.
   * 
   * @param {Object} [options]
   * @param {string} [options.inputPillSelector=".chat-input-pill"]
   * @param {string} [options.inputSelector="#chatInput"]
   * @param {string} [options.sendButtonSelector="#btnSendMessage"]
   */
  function initInputMicrointeractions(options = {}) {
    const gsapInstance = getGSAP();
    if (!gsapInstance || typeof document === 'undefined') return;

    const {
      inputPillSelector = ".chat-input-pill",
      inputSelector = "#chatInput",
      sendButtonSelector = "#btnSendMessage"
    } = options;

    const inputPill = document.querySelector(inputPillSelector);
    const input = document.querySelector(inputSelector);
    const sendBtn = document.querySelector(sendButtonSelector);

    if (input && inputPill) {
      if (!input.dataset.gsapInputInit) {
        input.dataset.gsapInputInit = "true";

        // Foco: transição suave para azul de destaque
        input.addEventListener("focus", () => {
          gsapInstance.to(inputPill, {
            borderColor: "#00A3E0",
            boxShadow: "0 0 0 3px rgba(0, 163, 224, 0.18), 0 4px 20px rgba(8, 33, 66, 0.08)",
            duration: 0.2,
            ease: "power2.out"
          });
        });

        // Blur: retorno suave
        input.addEventListener("blur", () => {
          gsapInstance.to(inputPill, {
            borderColor: "var(--border-color, #E2E8F0)",
            boxShadow: "0 4px 16px rgba(0, 0, 0, 0.03)",
            duration: 0.2,
            ease: "power2.out"
          });
        });
      }
    }

    if (sendBtn && !sendBtn.dataset.gsapBtnInit) {
      sendBtn.dataset.gsapBtnInit = "true";
      const svgArrow = sendBtn.querySelector("svg");

      // Hover: scale 1 -> 1.08 + rotação de -5° na seta
      sendBtn.addEventListener("mouseenter", () => {
        if (prefersReducedMotion()) return;
        gsapInstance.to(sendBtn, {
          scale: 1.08,
          duration: 0.2,
          ease: "back.out(2)",
          overwrite: "auto"
        });
        if (svgArrow) {
          gsapInstance.to(svgArrow, {
            rotation: -5,
            duration: 0.2,
            ease: "power2.out",
            transformOrigin: "center center"
          });
        }
      });

      sendBtn.addEventListener("mouseleave", () => {
        if (prefersReducedMotion()) return;
        gsapInstance.to(sendBtn, {
          scale: 1.0,
          duration: 0.2,
          ease: "power2.out",
          overwrite: "auto"
        });
        if (svgArrow) {
          gsapInstance.to(svgArrow, {
            rotation: 0,
            duration: 0.2,
            ease: "power2.out"
          });
        }
      });

      // Click: pequeno "pulse" (scale 1 -> 0.9 -> 1.1 -> 1 em 0.25s)
      sendBtn.addEventListener("pointerdown", () => {
        if (prefersReducedMotion()) return;
        triggerSendButtonPulse(sendBtn);
      });
    }
  }

  /**
   * Dispara o pulse tátil no botão de envio.
   */
  function triggerSendButtonPulse(buttonEl) {
    const gsapInstance = getGSAP();
    if (!gsapInstance || prefersReducedMotion()) return;

    const btn = buttonEl || document.querySelector("#btnSendMessage");
    if (!btn) return;

    gsapInstance.timeline()
      .to(btn, { scale: 0.9, duration: 0.07, ease: "power2.in" })
      .to(btn, { scale: 1.1, duration: 0.1, ease: "power2.out" })
      .to(btn, { scale: 1.0, duration: 0.08, ease: "power2.inOut" });
  }

  // -------------------------------------------------------------------------
  // 5. CARD "SEUS DADOS ESTÃO PROTEGIDOS" & ESCUDO BREATHING
  // -------------------------------------------------------------------------

  /**
   * Inicializa o card de segurança inferior da sidebar:
   *  - Entrada com delay: fade + y: 10 -> 0, duration: 0.3s
   *  - Escudo com loop "breathing": scale 1 -> 1.03 -> 1 a cada 2s
   * 
   * @param {Object} [options]
   * @param {string} [options.cardSelector=".sidebar-lgpd-card"]
   * @param {string} [options.iconSelector=".lgpd-icon"]
   */
  function initSidebarShieldCard(options = {}) {
    const gsapInstance = getGSAP();
    if (!gsapInstance || typeof document === 'undefined') return null;

    const {
      cardSelector = ".sidebar-lgpd-card",
      iconSelector = ".lgpd-icon"
    } = options;

    const card = document.querySelector(cardSelector);
    if (!card) return null;

    const icon = card.querySelector(iconSelector);

    // Entrada com leve delay
    if (!prefersReducedMotion()) {
      gsapInstance.fromTo(card,
        { opacity: 0, y: 10 },
        { opacity: 1, y: 0, duration: 0.3, delay: 0.45, ease: "power2.out" }
      );
    } else {
      gsapInstance.to(card, { opacity: 1, duration: 0.15 });
    }

    // Breathing loop no escudo (se acessibilidade permitir)
    if (icon && !prefersReducedMotion()) {
      registerVisibilityHandler();

      const shieldTl = gsapInstance.timeline({
        repeat: -1,
        yoyo: true
      });

      shieldTl.to(icon, {
        scale: 1.03,
        duration: 2.0,
        ease: "sine.inOut"
      });

      activeLoopTimelines.add(shieldTl);
      return shieldTl;
    }

    return null;
  }

  // -------------------------------------------------------------------------
  // 6. INICIALIZADOR GERAL (initAllHomeInteractions)
  // -------------------------------------------------------------------------

  function initAllHomeInteractions() {
    registerVisibilityHandler();
    initCardMicrointeractions();
    initInputMicrointeractions();
    initBadgePulse();
    initSidebarShieldCard();
  }

  // -------------------------------------------------------------------------
  // 7. SUPORTE A REACT (useHomeInteractions)
  // -------------------------------------------------------------------------

  function createReactHooks(ReactInstance) {
    if (!ReactInstance || !ReactInstance.useRef || !ReactInstance.useEffect) {
      return {};
    }

    const { useRef, useEffect, useCallback } = ReactInstance;

    function useHomeInteractions() {
      const activeTimelineRef = useRef(null);

      useEffect(() => {
        initAllHomeInteractions();
        return () => {
          if (activeTimelineRef.current) {
            activeTimelineRef.current.kill();
          }
        };
      }, []);

      const playEntrance = useCallback((options = {}) => {
        if (activeTimelineRef.current) activeTimelineRef.current.kill();
        activeTimelineRef.current = animateHomeEntrance(options);
        return activeTimelineRef.current;
      }, []);

      const moveSidebarIndicator = useCallback((targetEl) => {
        animateNavActiveIndicator(targetEl);
      }, []);

      const pulseSend = useCallback((btnEl) => {
        triggerSendButtonPulse(btnEl);
      }, []);

      return {
        playEntrance,
        moveSidebarIndicator,
        pulseSend
      };
    }

    return { useHomeInteractions };
  }

  const reactHooks = typeof window !== 'undefined' && window.React
    ? createReactHooks(window.React)
    : {};

  return {
    animateHomeEntrance,
    initCardMicrointeractions,
    animateNavActiveIndicator,
    initBadgePulse,
    initInputMicrointeractions,
    triggerSendButtonPulse,
    initSidebarShieldCard,
    initAllHomeInteractions,
    prefersReducedMotion,
    createReactHooks,
    ...reactHooks
  };
});

