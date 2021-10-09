import random

class Igralec:
    """
    def __init__(self, nabor):
        self.igralec = nabor
        for ime in nabor:
            self.ime = nabor[0]
        for ime in nabor:
            self.tocke = nabor[1]
        for ime in nabor:
            self.radelci = nabor[2]
        for ime in nabor:
            self.stanje_tock = nabor[1][-1]
    """
    
    def __init__(self, ime):
        self.ime = ime
        self.tocke = [0]
        self.radelci = 0
    '''

    def __init__(self, ime):
        self.ime = ime
        pike = [0]
        for i in range(random.randint(5,10)):
            pike.append(random.randint(1,10)*10)
        self.tocke = pike
        self.radelci = 7
    '''


class Igralec(Igralec):
    def dodaj_tocke(self, tocke):
        self.tocke.append(self.tocke[-1] + tocke)
        if len(self.tocke) > 20:
            popped = self.tocke.pop(0)
            print("popali smo ", popped)
            #ce zelimo seveda
        return self.tocke

    def dodaj_radelc(self):
        self.radelci += 1
        return self.radelci

    def izbrisi_radelc(self):
        self.radelci -= 1
        return self.radelci

    def trenutne_tocke(self):
        return self.tocke[-1]

    def razlika(self):
        razlika1 = input("Kolikšna je bila razlika?\nVnesi razliko: ")
        if razlika1.replace("-","").isnumeric():
            return int(razlika1)
        else:
            print(f'Žal "{razlika1}" ni število, poskusi ponovno!')
            return self.razlika()

    def igra1(self):
        igra11 = input("Katero igro ste igrali?\nIgra: ")
        if igra11 == "ena" or igra11 == "dva" or igra11 == "tri" or igra11 == "solo ena" or igra11 == "solo dva" or igra11 == "solo tri" or igra11 == "berač" or igra11 == "solobrez" or igra11 == "valat":
            return igra11
        else:
            print(f'Žal "{igra11}" ni veljavna igra, poskusi ponovno!')
            return self.igra1()


    def igra_s_parametri(self, igra1, razlika1=0,dodatne_tocke=0, zmaga=True, soigralec=None):
        values_iger = {
            "tri": 10,
            "dva": 20,
            "ena": 30,
            "solo tri": 40,
            "solo dva": 50,
            "solo ena": 60,
            "berac": 70,
            "solo brez": 80,
            "valat": 250
        }

        vrednost_igre = values_iger[igra1]

        
        if igra1 == "valat" or igra1 == "berac":
            if not zmaga:
                vrednost_igre *= -1
            
            score = vrednost_igre

        else:
            if not zmaga:
                vrednost_igre *= -1
                razlika1 *= -1

            score = vrednost_igre + razlika1 + dodatne_tocke

        if self.radelci > 0:
            score *= 2
            if zmaga:
                self.izbrisi_radelc()
        
        if igra1 == "solo brez" or igra1 == "berac" or igra1 == "valat" or igra1 == "klop":
            self.dodaj_radelc()

        self.dodaj_tocke(score)        
        print(self.tocke, self.trenutne_tocke(), self.radelci)
        if not soigralec == None:
            soigralec.dodaj_tocke(score)
            print(soigralec.tocke, soigralec.trenutne_tocke(), soigralec.radelci)







##############################################################################################################################################
##############################################################################################################################################
    def igra(self):
        
        values_iger = {
            "tri": 10,
            "dva": 20,
            "ena": 30,
            "solo tri": 40,
            "solo dva": 50,
            "solo ena": 60,
            "berac": 70,
            "berač": 70,
            "solo brez": 80,
            "valat": 250,
            "klop": 0
        }
        
        ##slucajni valat ipd. izjeme
        zmaga = "DA"

        igra1 = input("Katero igro ste igrali?\nIgra: ")
        while not igra1 in values_iger:
            igra1 = input("To ni veljavna igra.\nIgra: ")

        if igra1 == "berač":
            igra1 = "berac"

        vrednost_igre = values_iger[igra1]

        if igra1 == "klop":
            klop_razlika = input("Koliko točk si zbral pri klopu?\nTočke: ")
            while not klop_razlika.replace("-","").isnumeric():
                klop_razlika = input(f"Žal '{klop_razlika}' ni število, poskusi ponovno!\nTočke: ")
            score = int(klop_razlika) * -1
            zmaga = "NE"    ##razen ce...

        elif igra1 == "valat" or igra1 == "berac":
            zmaga = input("Ali ste zmagali(DA/NE)?\n")
            while not (zmaga == "DA" or zmaga == "NE"):
                zmaga = input("Neveljaven odgovor, poskusite ponovno.\n")
            
            if zmaga == "NE":
                vrednost_igre *= -1

            score = vrednost_igre

        else:    
            razlika1 = input("Kolikšna je bila razlika?\nVnesi razliko: ")
            while not razlika1.replace("-","").isnumeric():
                razlika1 = input(f"Žal '{razlika1}' ni število, poskusi ponovno!\nVnesi razliko: ")

            if int(razlika1) == 0:
                zmaga = input("Ali ste zmagali(DA/NE)?\n")
                while not (zmaga == "DA" or zmaga == "NE"):
                    zmaga = input("Neveljaven odgovor, poskusite ponovno.\n")
                if zmaga == "NE":
                    vrednost_igre *= -1
            
            dodatne_tocke = input("Koliko dodatnih točk ste dobili (ali morda izgubili)?\nDodatne točke: ")
            while not dodatne_tocke.replace("-","").isnumeric():
                dodatne_tocke = input(f"Žal '{dodatne_tocke}' ni število, poskusi ponovno!\nDodatne točke: ")

            if int(razlika1) < 0:
                vrednost_igre *= -1
                zmaga = "NE"

            score = vrednost_igre + int(razlika1) + int(dodatne_tocke)

        if self.radelci > 0:
            score *= 2
            if (zmaga == "DA"):
                self.izbrisi_radelc()

        if igra1 == "solo brez" or igra1 == "berac" or igra1 == "valat" or igra1 == "klop":
            self.dodaj_radelc()

        self.dodaj_tocke(score)
        print(self.tocke, self.trenutne_tocke(), self.radelci)
       

        
            
        

    
    



matevz = Igralec(("Matevž",[0],0))